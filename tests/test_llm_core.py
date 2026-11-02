"""Tests for pricing, retry/back-off, caching and the mock client."""

import pytest

from swep.errors import LLMCallError
from swep.llm import PriceTable, ResponseCache, RetryPolicy, call_with_retry
from swep.llm.mock import MockLLMClient, classify_comment
from swep.llm.parsing import parse_stage1
from swep.schema import Stage1Label


class TestPricing:
    def setup_method(self):
        self.prices = PriceTable(
            {"gpt-4.1": {"input": 2.0, "output": 8.0}, "o3-mini": {"input": 1.1, "output": 4.4}},
            default={"input": 1.0, "output": 1.0},
        )

    def test_exact_model(self):
        assert self.prices.cost("o3-mini", 1_000_000, 0) == pytest.approx(1.1)

    def test_dated_snapshot_uses_the_longest_prefix(self):
        assert self.prices.cost("gpt-4.1-2025-04-14", 1_000_000, 0) == pytest.approx(2.0)

    def test_unknown_model_uses_the_default(self):
        assert self.prices.cost("mystery", 1_000_000, 1_000_000) == pytest.approx(2.0)

    def test_input_and_output_are_both_priced(self):
        assert self.prices.cost("gpt-4.1", 500_000, 250_000) == pytest.approx(1.0 + 2.0)


class TestRetryPolicy:
    def test_delays_grow_exponentially_and_are_capped(self):
        policy = RetryPolicy(max_attempts=5, base_delay_s=2.0, max_delay_s=6.0, jitter_s=0.0)
        assert [policy.delay_for(attempt) for attempt in (1, 2, 3, 4)] == [2.0, 4.0, 6.0, 6.0]

    def test_jitter_stays_within_its_bound(self):
        policy = RetryPolicy(base_delay_s=1.0, max_delay_s=10.0, jitter_s=0.5)
        for attempt in range(1, 4):
            delay = policy.delay_for(attempt)
            assert delay >= policy.base_delay_s

    def test_retry_then_success(self):
        calls = {"n": 0}
        slept = []

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMCallError("transient", retryable=True)
            return "ok"

        result = call_with_retry(
            flaky,
            RetryPolicy(max_attempts=5, base_delay_s=0.01, jitter_s=0),
            is_retryable=lambda exc: exc.retryable,
            sleep=slept.append,
        )
        assert result == "ok"
        assert calls["n"] == 3
        assert len(slept) == 2

    def test_non_retryable_error_is_raised_immediately(self):
        calls = {"n": 0}

        def failing():
            calls["n"] += 1
            raise LLMCallError("denied", retryable=False)

        with pytest.raises(LLMCallError):
            call_with_retry(
                failing,
                RetryPolicy(max_attempts=5),
                is_retryable=lambda exc: exc.retryable,
                sleep=lambda _: None,
            )
        assert calls["n"] == 1

    def test_retry_budget_is_exhausted(self):
        calls = {"n": 0}

        def always_failing():
            calls["n"] += 1
            raise LLMCallError("rate limited", retryable=True)

        with pytest.raises(LLMCallError):
            call_with_retry(
                always_failing,
                RetryPolicy(max_attempts=3, base_delay_s=0.01, jitter_s=0),
                is_retryable=lambda exc: exc.retryable,
                sleep=lambda _: None,
            )
        assert calls["n"] == 3


class TestResponseCache:
    def test_put_then_get(self, tmp_path):
        cache = ResponseCache(tmp_path / "cache.sqlite3")
        key = cache.make_key("gpt-4.1", 0, 100, [{"role": "user", "content": "hi"}])
        cache.put(key, "gpt-4.1", {"text": '{"label": "None"}'})
        assert cache.get(key) == {"text": '{"label": "None"}'}
        assert cache.count() == 1
        cache.close()

    def test_miss_returns_none(self, tmp_path):
        cache = ResponseCache(tmp_path / "cache.sqlite3")
        assert cache.get("absent") is None
        cache.close()

    def test_key_sensitivity(self):
        messages = [{"role": "user", "content": "hi"}]
        base = ResponseCache.make_key("gpt-4.1", 0, 100, messages)
        assert base != ResponseCache.make_key("o3-mini", 0, 100, messages)
        assert base != ResponseCache.make_key("gpt-4.1", 1, 100, messages)
        assert base != ResponseCache.make_key("gpt-4.1", 0, 200, messages)
        assert base == ResponseCache.make_key("gpt-4.1", 0, 100, messages)

    def test_disabled_cache_is_a_no_op(self, tmp_path):
        cache = ResponseCache(tmp_path / "cache.sqlite3", enabled=False)
        key = cache.make_key("gpt-4.1", 0, 100, [])
        cache.put(key, "gpt-4.1", {"text": "x"})
        assert cache.get(key) is None

    def test_entries_survive_reopening(self, tmp_path):
        path = tmp_path / "cache.sqlite3"
        first = ResponseCache(path)
        key = first.make_key("gpt-4.1", 0, 100, [{"role": "user", "content": "x"}])
        first.put(key, "gpt-4.1", {"text": "persisted"})
        first.close()

        second = ResponseCache(path)
        assert second.get(key) == {"text": "persisted"}
        second.close()


class TestMockHeuristics:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("LGTM, thanks!", Stage1Label.NONE),
            ("Please improve the readability here.", Stage1Label.GENERAL),
            ("The `parse_config` function should validate the file extension.", Stage1Label.VALID),
            ("This loop leaks the file handle.", Stage1Label.VALID),
        ],
    )
    def test_classify_comment(self, text, expected):
        label, _, _ = classify_comment(text)
        assert label is expected

    def test_mock_output_parses_through_the_normal_path(self, sample_records):
        client = MockLLMClient()
        response = client.complete(
            [{"role": "user", "content": "ignored"}],
            "gpt-4.1",
            context={"stage": "stage1", "record": sample_records[0]},
        )
        result = parse_stage1(response.text)
        assert result.label is Stage1Label.VALID
        assert result.issues

    def test_mock_requires_a_record(self):
        client = MockLLMClient()
        with pytest.raises(LLMCallError):
            client.complete([], "gpt-4.1", context={"stage": "stage1"})

    def test_mock_can_simulate_retryable_failures(self, sample_records):
        client = MockLLMClient(failures=["rate_limit", "timeout"])
        with pytest.raises(LLMCallError):
            client.complete([], "gpt-4.1", context={"stage": "stage1", "record": sample_records[0]})
        with pytest.raises(LLMCallError):
            client.complete([], "gpt-4.1", context={"stage": "stage1", "record": sample_records[0]})
        response = client.complete(
            [], "gpt-4.1", context={"stage": "stage1", "record": sample_records[0]}
        )
        assert response.text.startswith("{")
