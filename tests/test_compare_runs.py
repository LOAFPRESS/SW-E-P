"""Tests for the A/B comparison script (``scripts/compare_runs.py``).

The script produces the numbers quoted in docs/rq2-results.md, and it has already
been wrong once (the binary view was fed labels that had been binarised twice). The
tests pin the pieces that decision depends on: the four views, the per-view
metrics, and the agreement/transition bookkeeping.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_runs.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("compare_runs", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _row(cid, final, stage1=None, stage2="", source="hunk-level", error=""):
    return {
        "comment_id": cid,
        "final_label": final,
        "stage1_label": stage1 if stage1 is not None else "",
        "stage2_label": stage2,
        "source": source,
        "error": error,
    }


class TestLabelHelpers:
    def test_stage1_of(self, module):
        assert module.stage1_of("Valid-Fully") == "Valid"
        assert module.stage1_of("General") == "General"
        assert module.stage1_of(None) is None
        assert module.stage1_of("") is None

    def test_stage2_of(self, module):
        assert module.stage2_of("Valid-Partially") == "Valid-Partially"
        assert module.stage2_of("General") is None
        assert module.stage2_of(None) is None

    def test_as_binary(self, module):
        assert module.as_binary("Valid-Fully") == "Addressed"
        assert module.as_binary("Valid-Partially") == "Addressed"
        assert module.as_binary("Valid-Unadressed") == "Not-Addressed"
        assert module.as_binary("None") == "Not-Addressed"


class TestViewPairs:
    def test_builds_the_four_views(self, module):
        rows = {
            "1": _row("1", "Valid-Fully", stage1="Valid", stage2="Valid-Fully"),
            "2": _row("2", "General", stage1="General"),
            "3": _row("3", "Valid-Unadressed", stage1="Valid", stage2="Valid-Unadressed"),
        }
        gold = {"1": "Valid-Fully", "2": "General", "3": "Valid-Unadressed"}
        views = module.view_pairs(rows, gold)
        assert len(views["six_class"]) == 3
        assert len(views["binary"]) == 3
        # stage-2 only counts comments whose gold label is Valid-*
        assert len(views["stage2"]) == 2
        assert views["binary"][0] == ("Addressed", "Addressed")

    def test_skips_rows_without_gold(self, module):
        rows = {"1": _row("1", "None"), "9": _row("9", "None")}
        views = module.view_pairs(rows, {"1": "None"})
        assert len(views["six_class"]) == 1

    def test_binary_view_is_not_double_binarised(self, module):
        """Regression: pass six-class labels, never an already-binary view."""
        rows = {"1": _row("1", "Valid-Partially", stage1="Valid")}
        views = module.view_pairs(rows, {"1": "Valid-Fully"})
        assert views["binary"] == [("Addressed", "Addressed")]


class TestMetrics:
    def test_perfect_prediction(self, module):
        views = {"six_class": [("None", "None"), ("General", "General")]}
        table = module.metrics_table(views, module.LABEL_SETS)
        assert table["six_class"]["accuracy"] == pytest.approx(1.0)
        # macro-F1 averages over the six-label universe, so the four absent classes
        # still drag it down to 2/6 - that is the documented behaviour, not a bug.
        assert table["six_class"]["macro_f1"] == pytest.approx(2.0 / 6.0)

    def test_perfect_prediction_of_one_view(self, module):
        views = {"binary": [("Addressed", "Addressed"), ("Not-Addressed", "Not-Addressed")]}
        table = module.metrics_table(views, module.LABEL_SETS)
        assert table["binary"]["accuracy"] == pytest.approx(1.0)
        assert table["binary"]["macro_f1"] == pytest.approx(1.0)

    def test_only_populated_views_appear(self, module):
        views = {"six_class": [("None", "None")], "stage1": [], "stage2": [], "binary": []}
        table = module.metrics_table(views, module.LABEL_SETS)
        assert list(table) == ["six_class"]

    def test_fmt_rounds_to_one_decimal(self, module):
        assert module.fmt(0.8666) == "86.7%"


class TestAgreement:
    def test_counts_and_transitions(self, module):
        rows_a = {
            "1": _row("1", "General", stage1="General"),
            "2": _row("2", "None", stage1="None"),
            "3": _row("3", "Valid-Fully", stage1="Valid"),
        }
        rows_b = {
            "1": _row("1", "Valid-Unadressed", stage1="Valid"),  # changed
            "2": _row("2", "None", stage1="None"),  # same
            "3": _row("3", "Valid-Fully", stage1="Valid"),  # same
            "4": _row("4", "None"),  # only in b
        }
        out = module.agreement(rows_a, rows_b)
        assert out["shared"] == 3
        assert out["changed"] == 1
        assert out["agreement_rate"] == pytest.approx(2.0 / 3.0)
        assert out["stage1_changed"] == 1
        assert out["transitions"] == {"General -> Valid-Unadressed": 1}
        assert out["examples"][0]["comment_id"] == "1"

    def test_identical_runs(self, module):
        rows = {"1": _row("1", "General", stage1="General")}
        out = module.agreement(rows, rows)
        assert out["agreement_rate"] == 1.0
        assert out["changed"] == 0

    def test_no_shared_rows(self, module):
        out = module.agreement({"1": _row("1", "None")}, {"2": _row("2", "None")})
        assert out["shared"] == 0
        assert out["agreement_rate"] == 0.0


class TestReaders:
    def test_read_run_skips_error_and_blank_rows(self, module, tmp_path):
        path = tmp_path / "run.csv"
        path.write_text(
            "comment_id,final_label,stage1_label,stage2_label,source,error\n"
            "1,Valid-Fully,Valid,Valid-Fully,hunk-level,\n"
            "2,,,,\n"
            "3,None,None,,hunk-level,provider error\n",
            encoding="utf-8",
        )
        rows = module.read_run(str(path))
        assert set(rows) == {"1"}

    def test_read_gold_ignores_unlabelled_records(self, module, tmp_path):
        path = tmp_path / "gold.jsonl"
        lines = [
            {"comment_id": "1", "gold_label": "Valid-Fully"},
            {"comment_id": "2", "gold_label": None},
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        gold = module.read_gold(str(path))
        assert gold == {"1": "Valid-Fully"}
