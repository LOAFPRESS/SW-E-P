"""Tests for the label-sensitivity script (DEV-12).

The script itself is exercised end to end by hand (it needs the Zenodo appendix
and a finished annotation run); these tests pin the parts that are easy to get
wrong: the id extraction, the kappa arithmetic, the rank distance, and the
markdown builder's tolerance for a payload without SHAP or without one label set.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rq3_label_sensitivity.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("rq3_label_sensitivity", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class TestCommentId:
    def test_strips_the_api_url(self, module):
        url = "https://api.github.com/repos/gfargo/coco/pulls/comments/1394464747"
        assert module._comment_id(url) == "1394464747"

    def test_keeps_a_plain_id(self, module):
        assert module._comment_id("1264656945") == "1264656945"


class TestAgreement:
    def test_counts_and_kappa(self, module):
        paper = {"1": 1, "2": 1, "3": 0, "4": 0, "5": 1}
        ours = {"1": 1, "2": 0, "3": 0, "4": 0, "5": 1}
        out = module.agreement(paper, ours)
        assert out["n"] == 5
        assert out["confusion"] == {"tp": 2, "tn": 2, "fp": 0, "fn": 1}
        assert out["agreement"] == pytest.approx(0.8)
        # pe = (2*3 + 2*3) / 25 = 0.48 -> (0.8 - 0.48) / 0.52
        assert out["kappa"] == pytest.approx((0.8 - 0.48) / 0.52, abs=1e-3)

    def test_perfect_agreement_gives_kappa_one(self, module):
        paper = {"a": 1, "b": 0, "c": 1}
        out = module.agreement(paper, {"a": 1, "b": 0, "c": 1})
        assert out["agreement"] == 1.0
        assert out["kappa"] == 1.0

    def test_ignores_ids_only_in_one_source(self, module):
        out = module.agreement({"1": 1, "9": 0}, {"1": 1, "8": 1})
        assert out["n"] == 1

    def test_empty_overlap(self, module):
        assert module.agreement({"1": 1}, {"2": 1}) == {"n": 0}


class TestRankDistance:
    def test_identical_rankings(self, module):
        names = ["a", "b", "c"]
        assert module.rank_distance(names, names) == {"n": 3, "mean_shift": 0.0}

    def test_reversed_ranking(self, module):
        out = module.rank_distance(["a", "b", "c"], ["c", "b", "a"])
        assert out["mean_shift"] == pytest.approx(1.33)  # rounded to two decimals

    def test_uses_only_shared_names(self, module):
        out = module.rank_distance(["a", "b"], ["a", "b", "z"])
        assert out["n"] == 2


class TestReport:
    def _payload(self, module):
        return {
            "shared_comment_ids": 110,
            "agreement": {
                "n": 110,
                "agreement": 0.927,
                "kappa": 0.835,
                "confusion": {"tp": 70, "tn": 32, "fp": 5, "fn": 3},
                "our_positive_rate": 0.682,
                "paper_positive_rate": 0.664,
            },
            "runs": [
                {
                    "labels": "paper labels",
                    "rows": 110,
                    "accuracy": 0.7273,
                    "accuracy_std": 0.0909,
                    "macro_f1": 0.6716,
                    "macro_f1_std": 0.1131,
                    "top": [["Is_Human", 0.05], ["Code_Text_Ratio", 0.04]],
                    "ranking": ["Is_Human", "Code_Text_Ratio"],
                },
                {
                    "labels": "our labels",
                    "rows": 110,
                    "accuracy": 0.7909,
                    "accuracy_std": 0.0843,
                    "macro_f1": 0.7364,
                    "macro_f1_std": 0.1101,
                    "top": [["Code_Text_Ratio", 0.06], ["Is_Human", 0.05]],
                    "ranking": ["Code_Text_Ratio", "Is_Human"],
                },
            ],
            "rank_shifts": [
                {"first": "paper labels", "second": "our labels", "n": 36, "mean_shift": 3.78},
                {"first": "paper labels", "second": "full 3,879-row run", "n": 10, "mean_shift": 8.8},
            ],
        }

    def test_contains_every_section(self, module):
        text = module.build_report(self._payload(module))
        for heading in ("# RQ3 label sensitivity", "## 0.", "## 1.", "## 2.", "## 3.", "## 4."):
            assert heading in text
        assert "92.7 %" in text
        assert "0.835" in text
        assert "3.78" in text
        assert "| 2 | Code_Text_Ratio | Is_Human |" in text

    def test_tolerates_missing_rank_shifts(self, module):
        payload = self._payload(module)
        payload["rank_shifts"] = []
        text = module.build_report(payload)
        assert "## 3." in text

    def test_tolerates_a_single_run(self, module):
        payload = self._payload(module)
        payload["runs"] = payload["runs"][:1]
        payload["rank_shifts"] = []
        text = module.build_report(payload)
        assert "paper labels" in text
        assert "our labels" not in text.split("## 3.")[0].split("## 2.")[1]


