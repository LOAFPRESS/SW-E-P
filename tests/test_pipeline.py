"""End-to-end tests of the two-stage pipeline with the mock/stub clients."""

import json

import pytest

from swep.errors import BudgetExceeded, ParseError
from swep.export import (
    compute_stability,
    evaluate_against_gold,
    summarize_run,
    write_annotations_csv,
)
from swep.llm import ResponseCache
from swep.llm.base import LLMClient, LLMResponse
from swep.llm.mock import MockLLMClient
from swep.logging_utils import JsonlWriter, setup_logger
from swep.metrics import observed_labels, per_source_report
from swep.pipeline import AnnotationPipeline, run_fingerprint
from swep.schema import CSV_COLUMNS

from conftest import make_record, write_config

VALID_STAGE1 = '{"label": "Valid", "issues": ["validate the extension"], "rationale": "Specific request."}'
VALID_STAGE2 = (
    '{"label": "Valid-Fully", "addressed_items": ["validate the extension"],'
    ' "unaddressed_items": [], "rationale": "Check added."}'
)


class StubClient(LLMClient):
    """Returns canned answers in order and records the calls it received."""

    name = "stub"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def complete(
        self, messages, model, temperature=0, max_output_tokens=1024, context=None
    ):
        self.calls.append({"model": model, "stage": (context or {}).get("stage"), "messages": messages})
        text = self.answers.pop(0) if self.answers else "no answer"
        return LLMResponse(text=text, model=model, prompt_tokens=100, completion_tokens=20)


@pytest.fixture(autouse=True)
def quiet_logger():
    setup_logger(None, level="CRITICAL", stream=False)


def make_pipeline(config, client, prompts, cache=None, request_log=None):
    return AnnotationPipeline(
        config, client, prompts, cache=cache, request_log=request_log, progress=False
    )


class TestHappyPath:
    def test_labels_and_counters(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        client = MockLLMClient()
        result = make_pipeline(config, client, prompts).run(
            [
                make_record("a", comment_text="`parse_config` should validate the extension."),
                make_record("b", comment_text="LGTM, thanks!"),
                make_record("c", comment_text="Please improve readability here."),
            ]
        )
        assert result.stats.processed == 3
        assert result.stats.completed == 3
        assert result.stats.failed == 0
        assert result.stats.llm_calls == 4  # 3 stage-1 + 1 stage-2
        assert result.stats.stage2_calls == 1
        assert result.stats.stopped_reason == "completed"
        assert result.ok is True

        labels = {item.comment_id: item.final_label for item in result.annotations}
        assert labels["a"].startswith("Valid-")
        assert labels["b"] == "None"
        assert labels["c"] == "General"

    def test_non_valid_comments_skip_stage_two(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        result = make_pipeline(config, MockLLMClient(), prompts).run(
            [make_record("b", comment_text="LGTM")]
        )
        annotation = result.annotations[0]
        assert annotation.stage1_label == "None"
        assert annotation.stage2_label == ""
        assert annotation.model_stage2 == ""
        assert annotation.input_tokens > 0

    def test_prompt_version_is_recorded_on_every_row(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        result = make_pipeline(config, MockLLMClient(), prompts).run([make_record("a")])
        assert result.annotations[0].prompt_version == "test-v1"
        assert result.prompt_fingerprint.startswith("test-v1:")


class TestCache:
    def test_second_run_is_served_entirely_from_cache(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        cache = ResponseCache(tmp_path / "cache.sqlite3")
        records = [make_record("a"), make_record("b", comment_text="LGTM")]

        first = make_pipeline(config, MockLLMClient(), prompts, cache=cache).run(records)
        second = make_pipeline(config, MockLLMClient(), prompts, cache=cache).run(records)

        assert first.stats.llm_calls == 3
        assert second.stats.llm_calls == 0
        assert second.stats.cache_hits == 3
        assert second.annotations[0].cached_calls == 2
        assert second.annotations[0].stage1_label == first.annotations[0].stage1_label
        assert second.stats.cost_usd == 0.0
        cache.close()


class TestBudget:
    def test_budget_stops_before_spending(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path, llm={"budget": {"max_usd": 0.000001}})
        result = make_pipeline(config, MockLLMClient(), prompts).run([make_record("a")])
        assert result.stats.stopped_reason == "budget_exceeded"
        assert result.stats.llm_calls == 0
        assert result.annotations == []
        assert result.ok is False

    def test_budget_exception_is_raised_by_a_single_record_call(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path, llm={"budget": {"max_usd": 0.000001}})
        pipeline = make_pipeline(config, MockLLMClient(), prompts)
        with pytest.raises(BudgetExceeded):
            pipeline.annotate_record(make_record("a"))


class TestResilience:
    def test_retryable_failures_are_retried(self, tmp_path, records_path, prompts):
        config = write_config(
            tmp_path,
            records_path,
            llm={"retry": {"max_attempts": 5, "base_delay_s": 0.001, "max_delay_s": 0.002, "jitter_s": 0}},
            run={"name": "retry-test"},
        )
        client = MockLLMClient(failures=["rate_limit", "timeout"])
        result = make_pipeline(config, client, prompts).run([make_record("b", comment_text="LGTM")])
        assert result.stats.retries == 2
        assert result.stats.failed == 0
        assert result.annotations[0].stage1_label == "None"

    def test_unparsable_answer_is_repaired(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path, llm={"max_parse_retries": 1})
        client = StubClient(["not json at all", VALID_STAGE1, VALID_STAGE2])
        result = make_pipeline(config, client, prompts).run([make_record("a")])
        assert result.stats.parse_retries == 1
        assert result.stats.completed == 1
        assert result.annotations[0].final_label == "Valid-Fully"
        assert [call["stage"] for call in client.calls] == ["stage1", "stage1-repair", "stage2"]

    def test_unparsable_answer_marks_only_that_record_failed(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path, llm={"max_parse_retries": 0})
        client = StubClient(["garbage"])
        result = make_pipeline(config, client, prompts).run([make_record("a")])
        assert result.stats.failed == 1
        annotation = result.annotations[0]
        assert annotation.error
        assert annotation.stage1_label == ""
        assert result.ok is True

    def test_abort_on_record_error_raises(self, tmp_path, records_path, prompts):
        config = write_config(
            tmp_path, records_path, run={"abort_on_record_error": True}, llm={"max_parse_retries": 0}
        )
        with pytest.raises(ParseError):
            make_pipeline(config, StubClient(["garbage"]), prompts).run([make_record("a")])


class TestAuditLog:
    def test_every_call_is_logged_without_secrets(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        log_path = tmp_path / "requests.jsonl"
        writer = JsonlWriter(log_path)
        try:
            make_pipeline(config, MockLLMClient(), prompts, request_log=writer).run([make_record("a")])
        finally:
            writer.close()

        lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [line["stage"] for line in lines] == ["stage1", "stage2"]
        for line in lines:
            assert line["comment_id"] == "a"
            assert line["prompt_version"] == "test-v1"
            assert {"model", "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms", "cached"} <= set(line)
        raw = log_path.read_text(encoding="utf-8")
        assert "sk-" not in raw
        assert "api_key" not in raw.lower()


class TestExport:
    def test_csv_round_trip_and_summary(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        result = make_pipeline(config, MockLLMClient(), prompts).run(
            [make_record("a"), make_record("b", comment_text="LGTM")]
        )
        csv_path = write_annotations_csv(result.annotations, tmp_path / "annotations.csv")
        header = csv_path.read_text(encoding="utf-8").splitlines()[0]
        assert header == ",".join(CSV_COLUMNS)

        predicted = {item.comment_id: item.final_label for item in result.annotations}
        evaluation = evaluate_against_gold(result.annotations, predicted)
        assert evaluation is not None
        assert evaluation["six_class"]["accuracy"] == 1.0
        assert evaluation["n"] == 2

        # A deliberately wrong gold label must be counted as a miss.
        wrong = dict(predicted)
        wrong["b"] = "Valid-Fully"
        assert evaluate_against_gold(result.annotations, wrong)["six_class"]["accuracy"] == 0.5

        summary = summarize_run(
            result,
            {"count": 2},
            config,
            prompts,
            run_fingerprint(config, prompts),
            extra={"evaluation": evaluation},
        )
        assert summary["labels"]["final_six_class"]["None"] == 1
        assert summary["pipeline"]["completed"] == 2
        assert summary["run_fingerprint"]


class TestPerSource:
    def test_groups_metrics_by_source(self):
        report = per_source_report(
            {
                "file-level": [("Valid-Fully", "Valid-Fully"), ("None", "None")],
                "hunk-level": [("General", "Valid-Fully")],
            }
        )
        assert set(report) == {"file-level", "hunk-level"}
        assert report["file-level"]["n"] == 2
        assert report["file-level"]["accuracy"] == 1.0
        assert report["hunk-level"]["accuracy"] == 0.0
        assert report["hunk-level"]["binary"]["accuracy"] == 0.0

    def test_skips_empty_groups_and_unlabelled_pairs(self):
        report = per_source_report({"human": [], "file-level": [("", "")]})
        assert report == {}

    def test_observed_labels_follow_canonical_order(self):
        labels = observed_labels(["Valid-Fully", "General"], ["None", "General"])
        assert labels == ["None", "General", "Valid-Fully"]

    def test_evaluation_carries_per_source_breakdown(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        result = make_pipeline(config, MockLLMClient(), prompts).run(
            [make_record("a"), make_record("b", comment_text="LGTM")]
        )
        predicted = {item.comment_id: item.final_label for item in result.annotations}
        sources = {"a": "file-level", "b": "hunk-level"}
        evaluation = evaluate_against_gold(result.annotations, predicted, sources=sources)
        assert evaluation["per_source"]["file-level"]["n"] == 1
        assert evaluation["per_source"]["hunk-level"]["n"] == 1
        # Without the source map there is no per-source section at all.
        assert "per_source" not in evaluate_against_gold(result.annotations, predicted)


class TestStability:
    def test_identical_runs_agree(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        records = [make_record("a")]
        runs = [make_pipeline(config, MockLLMClient(), prompts).run(records) for _ in range(2)]
        stability = compute_stability(runs)
        assert stability["repeats"] == 2
        assert stability["comparable_records"] == 1
        assert stability["agreement_rate"] == 1.0
        assert stability["unstable"] == []

    def test_disagreeing_runs_are_listed(self, tmp_path, records_path, prompts):
        config = write_config(tmp_path, records_path)
        records = [make_record("a")]
        first = make_pipeline(config, StubClient([VALID_STAGE1, VALID_STAGE2]), prompts).run(records)
        second = make_pipeline(
            config,
            StubClient(
                [
                    '{"label": "General", "issues": [], "rationale": "vague"}',
                ]
            ),
            prompts,
        ).run(records)
        stability = compute_stability([first, second])
        assert stability["agreement_rate"] == 0.0
        assert stability["unstable"][0]["comment_id"] == "a"
        assert stability["per_repeat_distribution"][0]["Valid-Fully"] == 1
        assert stability["per_repeat_distribution"][1]["General"] == 1
