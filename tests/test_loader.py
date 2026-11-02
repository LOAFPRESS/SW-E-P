"""Tests for dataset loading and column mapping (REQ-1.1)."""

import json

import pytest

from swep.data import describe_dataset, load_dataset
from swep.errors import DataValidationError

from conftest import write_jsonl


class TestFormats:
    def test_jsonl(self, records_path):
        records = load_dataset(records_path)
        assert [record.comment_id for record in records] == ["c-1", "c-2", "c-3"]
        assert records[0].source == "file-level"

    def test_json_array(self, tmp_path, records_path):
        rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
        path = tmp_path / "records.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        assert len(load_dataset(path)) == 3

    def test_json_object_with_records_key(self, tmp_path, records_path):
        rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
        path = tmp_path / "wrapped.json"
        path.write_text(json.dumps({"records": rows}), encoding="utf-8")
        assert len(load_dataset(path)) == 3

    def test_csv_with_aliases(self, tmp_path):
        path = tmp_path / "records.csv"
        path.write_text(
            "comment id,Source,comment\n"
            'c-1,human,"Please rename the variable"\n'
            'c-2,file-level,"LGTM"\n',
            encoding="utf-8",
        )
        records = load_dataset(path)
        assert [record.comment_text for record in records] == [
            "Please rename the variable",
            "LGTM",
        ]

    def test_unsupported_extension_requires_explicit_format(self, tmp_path):
        path = tmp_path / "records.dat"
        path.write_text("", encoding="utf-8")
        with pytest.raises(DataValidationError):
            load_dataset(path)


class TestColumnMapping:
    def test_explicit_mapping_wins_over_aliases(self, tmp_path):
        rows = [
            {
                "review_comment_id": "x-1",
                "comment_body": "should validate input",
                "origin": "human",
                "label": "Valid-Fully",
            }
        ]
        path = tmp_path / "records.jsonl"
        path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
        records = load_dataset(
            path,
            column_map={
                "comment_id": "review_comment_id",
                "comment_text": "comment_body",
                "source": "origin",
                "gold_label": "label",
            },
        )
        assert records[0].comment_id == "x-1"
        assert records[0].comment_text == "should validate input"
        assert records[0].gold_label == "Valid-Fully"

    def test_mapping_accepts_a_list_of_candidates(self, tmp_path):
        path = tmp_path / "records.jsonl"
        path.write_text(
            json.dumps({"id": "x-1", "body": "text", "source": "human"}) + "\n", encoding="utf-8"
        )
        records = load_dataset(path, column_map={"comment_text": ["missing_col", "body"]})
        assert records[0].comment_text == "text"


class TestValidation:
    def test_missing_mandatory_field_lists_available_columns(self, tmp_path):
        path = tmp_path / "records.jsonl"
        path.write_text(json.dumps({"comment_id": "x", "source": "human"}) + "\n", encoding="utf-8")
        with pytest.raises(DataValidationError) as excinfo:
            load_dataset(path)
        message = str(excinfo.value)
        assert "comment_text" in message
        assert "Available columns" in message
        assert "column_map" in message

    def test_invalid_json_line_reports_the_line_number(self, tmp_path):
        path = tmp_path / "records.jsonl"
        path.write_text('{"comment_id": "x"}\nnot json\n', encoding="utf-8")
        with pytest.raises(DataValidationError) as excinfo:
            load_dataset(path)
        assert "line 2" in str(excinfo.value)

    def test_missing_file(self, tmp_path):
        with pytest.raises(DataValidationError):
            load_dataset(tmp_path / "absent.jsonl")

    def test_empty_dataset_is_an_error(self, tmp_path):
        path = tmp_path / "records.jsonl"
        path.write_text("\n", encoding="utf-8")
        with pytest.raises(DataValidationError):
            load_dataset(path)


class TestLimitAndSplit:
    def test_limit_truncates(self, records_path):
        assert len(load_dataset(records_path, limit=2)) == 2

    def test_split_by_source_string(self, records_path):
        records = load_dataset(records_path, split="hunk-level")
        assert [record.comment_id for record in records] == ["c-3"]

    def test_split_by_mapping(self, records_path):
        records = load_dataset(records_path, split={"field": "source", "values": ["file-level"]})
        assert [record.comment_id for record in records] == ["c-1", "c-2"]

    def test_split_that_matches_nothing_fails_loudly(self, records_path):
        with pytest.raises(DataValidationError):
            load_dataset(records_path, split="no-such-source")

    def test_split_on_unknown_field_fails(self, records_path):
        with pytest.raises(DataValidationError):
            load_dataset(records_path, split={"field": "nope", "values": ["x"]})


class TestDescribe:
    def test_counts_by_source_and_flags(self, records_path):
        stats = describe_dataset(load_dataset(records_path))
        assert stats["count"] == 3
        assert stats["by_source"] == {"file-level": 2, "hunk-level": 1}
        assert stats["with_gold_label"] == 3
        assert stats["synthetic"] == 0


class TestZenodoColumns:
    """The appendix column names must map onto the record without a column_map."""

    def test_reviewed_path_aliases(self, tmp_path):
        path = write_jsonl(
            tmp_path / "rows.jsonl",
            [
                {
                    "comment_id": "z-1",
                    "source": "file-level",
                    "comment_text": "Please fix the extension check.",
                    "Diff_path": "pkg/mod.py",
                    "New_path": "pkg/renamed.py",
                }
            ],
        )
        records = load_dataset(path)
        assert records[0].reviewed_path == "pkg/mod.py"
        assert records[0].new_path == "pkg/renamed.py"

    def test_reviewed_path_is_counted_by_describe(self, tmp_path):
        path = write_jsonl(
            tmp_path / "rows.jsonl",
            [
                {
                    "comment_id": "z-1",
                    "source": "hunk-level",
                    "comment_text": "Rename it.",
                    "reviewed_path": "pkg/mod.py",
                },
                {
                    "comment_id": "z-2",
                    "source": "human",
                    "comment_text": "Rename it.",
                },
            ],
        )
        stats = describe_dataset(load_dataset(path))
        assert stats["with_reviewed_path"] == 1
