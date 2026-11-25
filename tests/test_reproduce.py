"""Offline tests for reproduction input checks and the Markdown renderer."""

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def module():
    path = HERE / "scripts" / "reproduce_all.py"
    spec = importlib.util.spec_from_file_location("reproduce_all", str(path))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _payload():
    """The smallest payload that exercises every branch of the renderer."""
    return {
        "generated_at": "2026-11-21T18:47:20+08:00",
        "commit": "24edf6cd8a1b2c3d4e5f60718293a4b5c6d7e8f9",
        "versions": {"python": "3.8.6", "pandas": "2.0.3"},
        "inputs": [{"name": "data/gold150.jsonl", "rows": 150,
                    "sha256": "e638b01f80da239b1111"}],
        "validate": "records: 150\n  file-level   50",
        "ab": {
            "metrics": {
                "v2": {"stage1": {"accuracy": 0.873, "macro_f1": 0.748}},
                "v2.1": {"stage1": {"accuracy": 0.913, "macro_f1": 0.808}},
            },
            "agreement": {"shared": 150, "changed": 20, "agreement_rate": 0.8667,
                          "stage1_changed": 13, "transitions": {}},
        },
        "paper_table": "| view | n |\n| --- | --- |",
        "rq3_all": {
            "rows": 3879,
            "cross_validation": {"n_features": 36, "accuracy_mean": 0.8876,
                                 "macro_f1_mean": 0.8484},
            "shap": {"importance": [{"feature": "Is_Human", "mean_abs_shap": 0.04218}]},
        },
        "rq3_ai": {
            "rows": 2990,
            "cross_validation": {"n_features": 33, "accuracy_mean": 0.9187,
                                 "macro_f1_mean": 0.6553},
            "shap": {"importance": []},
        },
        "conclusions": {
            "conclusions": {
                "overall": {"rows": 3879, "addressed": 973, "rate": 0.2508},
                "comment_length": [{"bucket": "<= 120 chars", "rows": 605,
                                    "addressed": 413, "rate": 0.6826}],
                "code_snippets": {"has_inline_code": {"rows": 2425, "addressed": 429,
                                                      "rate": 0.1769}},
                "trigger": {"manual": {"rows": 104, "addressed": 15, "rate": 0.1442}},
                "granularity": {"hunk-level": {"rows": 689, "addressed": 148,
                                               "rate": 0.2148}},
                "ai_only": {
                    "overall": {"rows": 2990, "addressed": 274, "rate": 0.0916},
                    "comment_length": [{"bucket": "<= 120 chars", "rows": 84,
                                        "addressed": 7, "rate": 0.0833}],
                },
            }
        },
    }


def test_claim_rows_handles_both_shapes(module):
    buckets = module._claim_rows([{"bucket": "a", "rows": 1, "addressed": 0, "rate": 0.0}])
    assert list(buckets)[0][0] == "a"
    groups = module._claim_rows({"g": {"rows": 2, "addressed": 1, "rate": 0.5}})
    assert list(groups)[0][0] == "g"
    assert list(module._claim_rows(None)) == []


def test_markdown_renders_every_section(module):
    text = module.markdown(_payload())
    for needle in ("# Reproduction bundle", "from commit `24edf6cd8`", "## Inputs",
                   "## RQ2 — dataset validation", "Agreement between the two prompts",
                   "## RQ3 — random forest and SHAP", "0.8876",
                   "## RQ3 — the four practical claims", "AI only, Human removed",
                   "docs/paper-deviations.md"):
        assert needle in text, needle
    assert text.count("| claim |") == 0  # tables are lower case, just a sanity check


def test_markdown_survives_missing_optional_blocks(module):
    payload = _payload()
    payload["rq3_ai"]["shap"]["importance"] = []
    payload["conclusions"]["conclusions"].pop("ai_only")
    text = module.markdown(payload)
    assert "AI only" in text
    assert "AI only, Human removed" not in text


@pytest.mark.parametrize("flags", [[], ["--recompute", "--rerun-llm"]])
def test_missing_reproduction_inputs(module, tmp_path, monkeypatch, capsys, flags):
    monkeypatch.setattr(module, "GOLD", tmp_path / "gold150.jsonl")
    module.GOLD.touch()
    monkeypatch.setattr(module, "FEATURES", tmp_path / "features.csv")
    monkeypatch.setattr(module, "LABELS", tmp_path / "labels.csv")
    monkeypatch.setattr(module, "RUN_V2", tmp_path / "deepseek-paper")
    monkeypatch.setattr(module, "RUN_V21", tmp_path / "deepseek-v21")
    monkeypatch.setattr(module, "RQ3_ALL", tmp_path / "all_reviews")
    monkeypatch.setattr(module, "RQ3_AI", tmp_path / "ai_only")
    monkeypatch.setattr(module, "OUT", tmp_path / "reproduction")

    with pytest.raises(SystemExit) as error:
        module.main(flags)

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert str(module.FEATURES) in stderr
    assert str(module.LABELS) in stderr
    assert str(module.GOLD) not in stderr
    for run_dir in (module.RUN_V2, module.RUN_V21):
        assert (str(run_dir / "annotations.csv") in stderr) == ("--rerun-llm" not in flags)
    for run_dir in (module.RQ3_ALL, module.RQ3_AI):
        assert (str(run_dir / "rq3_metrics.json") in stderr) == ("--recompute" not in flags)
    assert "docs/reproduction.md" in stderr
    assert not module.OUT.exists()
