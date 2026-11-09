"""CLI-level tests: exit codes, artifacts and overrides."""

import csv
from pathlib import Path

import pytest

from swep import cli

from conftest import write_config


@pytest.fixture
def config_path(tmp_path, records_path):
    write_config(tmp_path, records_path)
    return tmp_path / "config.yaml"


class TestValidateData:
    def test_reports_the_dataset(self, config_path, capsys):
        assert cli.main(["validate-data", "-c", str(config_path), "--quiet"]) == cli.EXIT_OK
        output = capsys.readouterr().out
        assert "records: 3" in output
        assert "file-level" in output


class TestAnnotate:
    def test_writes_the_expected_artifacts(self, config_path, tmp_path):
        code = cli.main(["annotate", "-c", str(config_path), "--quiet", "--write-report"])
        assert code == cli.EXIT_OK
        output_dir = tmp_path / "out"
        for name in ("annotations.csv", "summary.json", "requests.jsonl", "run.log", "run_report.md"):
            assert (output_dir / name).is_file(), name

    def test_csv_has_the_fixed_schema(self, config_path, tmp_path):
        cli.main(["annotate", "-c", str(config_path), "--quiet"])
        with (tmp_path / "out" / "annotations.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 3
        assert "final_label" in rows[0]
        assert "prompt_version" in rows[0]

    def test_limit_override_is_honoured(self, config_path, tmp_path):
        cli.main(["annotate", "-c", str(config_path), "--quiet", "--limit", "1"])
        with (tmp_path / "out" / "annotations.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1

    def test_dry_run_writes_nothing_and_reports_cost(self, config_path, tmp_path, capsys):
        code = cli.main(["annotate", "-c", str(config_path), "--quiet", "--dry-run"])
        assert code == cli.EXIT_OK
        assert not (tmp_path / "out" / "annotations.csv").exists()
        assert "dry run" in capsys.readouterr().out

    def test_summary_records_the_prompt_version(self, config_path, tmp_path):
        cli.main(["annotate", "-c", str(config_path), "--quiet"])
        import json

        summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
        assert "test-v1" in summary["prompts"]
        assert summary["pipeline"]["completed"] == 3

    def test_repeat_runs_report_stability(self, config_path, tmp_path, capsys):
        import json

        code = cli.main(["annotate", "-c", str(config_path), "--quiet", "--repeat", "2"])
        assert code == cli.EXIT_OK
        summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
        stability = summary["stability"]
        assert stability["repeats"] == 2
        assert stability["comparable_records"] == 3
        # The mock provider is deterministic, so every record must agree.
        assert stability["agreement_rate"] == 1.0
        assert len(stability["per_repeat_distribution"]) == 2
        assert "stability" in capsys.readouterr().out


class TestErrors:
    def test_missing_configuration_returns_config_error(self, tmp_path):
        code = cli.main(["annotate", "-c", str(tmp_path / "absent.yaml"), "--quiet"])
        assert code == cli.EXIT_CONFIG

    def test_openai_without_key_returns_config_error(self, config_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        code = cli.main(["annotate", "-c", str(config_path), "--quiet", "--provider", "openai"])
        assert code == cli.EXIT_CONFIG

    def test_missing_dataset_returns_config_error(self, tmp_path, monkeypatch):
        write_config(tmp_path, tmp_path / "absent.jsonl")
        code = cli.main(["annotate", "-c", str(tmp_path / "config.yaml"), "--quiet"])
        assert code == cli.EXIT_CONFIG


class TestParser:
    def test_default_command_is_annotate(self):
        assert cli.DEFAULT_COMMAND == "annotate"
        assert cli.build_parser().parse_args([]).command is None

    def test_subcommand_is_optional(self, config_path, tmp_path):
        # `run.py -c ...` (no subcommand) must behave like `run.py annotate -c ...`.
        code = cli.main(["-c", str(config_path), "--quiet"])
        assert code == cli.EXIT_OK
        assert (tmp_path / "out" / "annotations.csv").is_file()

    def test_help_mentions_both_commands(self, capsys):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["--help"])
        output = capsys.readouterr().out
        assert "annotate" in output
        assert "validate-data" in output
        assert "rq3" in output

    def test_rq3_subcommand_is_registered(self):
        args = cli.build_parser().parse_args(["rq3", "--ai-only"])
        assert args.command == "rq3"
        assert args.ai_only is True


ZENODO_MATRIX = Path(cli.__file__).resolve().parents[2].parent / "AIReviewActionAnalysis(Zenodo)" / "address_feature_matrix"


@pytest.mark.skipif(not ZENODO_MATRIX.is_dir(), reason="the Zenodo feature matrix is not available on this machine")
class TestRq3Command:
    def test_runs_the_reduced_experiment(self, tmp_path, capsys):
        # Two folds and ten trees keep the test fast; SHAP is skipped on purpose.
        code = cli.main(
            [
                "rq3",
                "--no-shap",
                "--no-plot",
                "--n-splits",
                "2",
                "--n-estimators",
                "10",
                "--output",
                str(tmp_path / "rq3"),
            ]
        )
        assert code == cli.EXIT_OK
        assert "rows: 3879" in capsys.readouterr().out
        assert (tmp_path / "rq3" / "rq3_metrics.json").is_file()

    def test_missing_input_returns_a_config_error(self, tmp_path, capsys):
        code = cli.main(["rq3", "--zenodo-root", str(tmp_path / "nope"), "--output", str(tmp_path / "out")])
        assert code == cli.EXIT_CONFIG
        assert "rq3" in capsys.readouterr().err
