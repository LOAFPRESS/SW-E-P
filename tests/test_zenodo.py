"""Tests for building the gold-150 dataset from the Zenodo appendix (RQ2).

The real package lives outside the repository, so these tests build a miniature
Zenodo tree with the same file names, columns and label codes.  They cover the
three things that can silently corrupt a reproduction: the inner join, the label
code mapping, and the URL parsing that fills ``repo``/``pr_number``.
"""

import csv
import json
from pathlib import Path

import pytest

from swep.data.loader import load_dataset
from swep.data.zenodo import (
    GOLD_LABELS,
    build_gold_records,
    normalise_cell,
    parse_comment_url,
    write_jsonl,
    write_provenance,
)
from swep.errors import DataValidationError

INPUT_COLUMNS = [
    "source_action",
    "Comment_URL",
    "Comment_HTML_URL",
    "Diff_path",
    "New_path",
    "Body",
    "Diff_hunk",
    "Change_Until_Merged",
]

LABEL_COLUMNS = ["Comment_URL", "Final Result"]


def _write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _row(url, html="", body="Please fix the `parse_config` check.", diff="@@ -1 +1 @@\n-x\n+y\n",
         changes="@@ -1 +1 @@\n-x\n+y\n", path="pkg/mod.py", new_path="", action="anc95/ChatGPT-CodeReview"):
    return {
        "source_action": action,
        "Comment_URL": url,
        "Comment_HTML_URL": html,
        "Diff_path": path,
        "New_path": new_path,
        "Body": body,
        "Diff_hunk": diff,
        "Change_Until_Merged": changes,
    }


def _make_zenodo_tree(root, sources):
    """Write one input CSV and one label CSV per source.

    ``sources`` maps a source name onto ``(input_stem, label_stem, rows, labels)``
    where ``rows`` are input dicts and ``labels`` are ``(url, code)`` pairs.
    """
    for input_stem, label_stem, rows, labels in sources.values():
        _write_csv(root / "llm_analysis" / "input" / ("%s.csv" % input_stem), INPUT_COLUMNS, rows)
        _write_csv(
            root / "llm_analysis" / "labeled" / ("%s.csv" % label_stem),
            LABEL_COLUMNS,
            [{"Comment_URL": url, "Final Result": code} for url, code in labels],
        )
    return root


@pytest.fixture
def zenodo_root(tmp_path):
    api = "https://api.github.com/repos/demo/repo/pulls/comments/%d"
    html = "https://github.com/demo/repo/pull/7#discussion_r%d"
    file_rows = [
        _row(api % 101, html % 101),
        _row(api % 102, html % 102, changes="File_Deleted"),
    ]
    hunk_rows = [_row(api % 201, html % 201, changes="nan")]
    human_rows = [
        _row(api % 301, html % 301, path="", new_path="pkg/renamed.py", body="LGTM, thanks!"),
    ]
    return _make_zenodo_tree(
        tmp_path,
        {
            "file-level": (
                "sampled_file_level_review",
                "(resolved)sampled_file_level_review",
                file_rows,
                [(api % 101, "2,2"), (api % 102, "2,0")],
            ),
            "hunk-level": (
                "sampled_patch_level_review",
                "(resolved)sampled_patch_level_review",
                hunk_rows,
                [(api % 201, "1")],
            ),
            "human": (
                "sampled_human_review",
                "(resolved)sampled_human_review",
                human_rows,
                [(api % 301, "0")],
            ),
        },
    )


class TestCommentUrl:
    def test_api_pull_request_comment(self):
        repo, pr, comment = parse_comment_url(
            "https://api.github.com/repos/anc95/ChatGPT-CodeReview/pulls/comments/1876543210"
        )
        assert repo == "anc95/ChatGPT-CodeReview"
        assert comment == "1876543210"
        assert pr is None

    def test_api_issue_comment(self):
        repo, _, comment = parse_comment_url(
            "https://api.github.com/repos/o/r/issues/comments/42"
        )
        assert repo == "o/r"
        assert comment == "42"

    def test_html_url_carries_pr_and_comment_id(self):
        repo, pr, comment = parse_comment_url(
            "https://github.com/coderabbitai/ai-pr-reviewer/pull/1234#discussion_r5678"
        )
        assert repo == "coderabbitai/ai-pr-reviewer"
        assert pr == "1234"
        assert comment == "5678"

    def test_garbage_url_degrades_to_empty(self):
        assert parse_comment_url("") == (None, None, "")
        repo, pr, comment = parse_comment_url("not a url")
        assert (repo, pr, comment) == (None, None, "")


class TestNormaliseCell:
    def test_empty_markers_become_empty_string(self):
        for value in (None, "", "  ", "nan", "NaN", "None", "n/a", "<NA>"):
            assert normalise_cell(value) == ""

    def test_real_values_are_stripped_not_dropped(self):
        assert normalise_cell("  def f(): pass  ") == "def f(): pass"

    def test_deleted_sentinel_survives(self):
        assert normalise_cell("File_Deleted") == "File_Deleted"


class TestGoldCodeMapping:
    def test_all_six_codes_are_mapped(self):
        assert GOLD_LABELS == {
            "0": "None",
            "1": "General",
            "2,-1": "Valid-Uncertain",
            "2,0": "Valid-Unaddressed",
            "2,1": "Valid-Partially",
            "2,2": "Valid-Fully",
        }


class TestBuild:
    def test_records_are_built_with_labels_and_context(self, zenodo_root):
        records, stats = build_gold_records(zenodo_root)
        assert len(records) == 4
        by_source = {}
        for record in records:
            by_source.setdefault(record.source, []).append(record)
        assert sorted(by_source) == sorted(["file-level", "hunk-level", "human"])
        assert len(by_source["file-level"]) == 2

        fully = [r for r in records if r.gold_label == "Valid-Fully"][0]
        assert fully.comment_id == "101"
        assert fully.repo == "demo/repo"
        assert fully.pr_number == "7"
        assert fully.reviewed_path == "pkg/mod.py"
        assert fully.synthetic is False
        assert "parse_config" in fully.comment_text

    def test_stats_record_provenance(self, zenodo_root):
        _, stats = build_gold_records(zenodo_root)
        assert stats["count"] == 4
        assert stats["per_source"] == {"file-level": 2, "hunk-level": 1, "human": 1}
        assert stats["label_codes"] == {"0": 1, "1": 1, "2,0": 1, "2,2": 1}
        assert stats["labels"] == {
            "General": 1,
            "None": 1,
            "Valid-Fully": 1,
            "Valid-Unaddressed": 1,
        }
        assert stats["deleted_file_rows"] == 1
        assert stats["duplicate_comment_ids"] == 0
        assert len(stats["files"]) == 6
        assert all(len(digest) == 64 for digest in stats["files"].values())

    def test_empty_cells_become_empty_strings(self, zenodo_root):
        records, _ = build_gold_records(zenodo_root)
        hunk = [r for r in records if r.source == "hunk-level"][0]
        assert hunk.subsequent_changes == ""  # the CSV said "nan"

    def test_missing_new_path_is_none(self, zenodo_root):
        records, _ = build_gold_records(zenodo_root)
        file_level = [r for r in records if r.source == "file-level"][0]
        assert file_level.new_path is None
        human = [r for r in records if r.source == "human"][0]
        assert human.new_path == "pkg/renamed.py"

    def test_source_filter(self, zenodo_root):
        records, stats = build_gold_records(zenodo_root, sources=["human"])
        assert [r.source for r in records] == ["human"]
        assert stats["per_source"] == {"human": 1}

    def test_unknown_label_code_stops_the_build(self, zenodo_root):
        label_file = (
            zenodo_root / "llm_analysis" / "labeled" / "(resolved)sampled_human_review.csv"
        )
        _write_csv(
            label_file,
            LABEL_COLUMNS,
            [{"Comment_URL": "https://api.github.com/repos/demo/repo/pulls/comments/301",
              "Final Result": "3,9"}],
        )
        with pytest.raises(DataValidationError) as excinfo:
            build_gold_records(zenodo_root)
        assert "3,9" in str(excinfo.value)

    def test_unmatched_label_is_reported_not_dropped(self, zenodo_root):
        label_file = (
            zenodo_root / "llm_analysis" / "labeled" / "(resolved)sampled_human_review.csv"
        )
        _write_csv(
            label_file,
            LABEL_COLUMNS,
            [{"Comment_URL": "https://api.github.com/repos/demo/repo/pulls/comments/999",
              "Final Result": "0"}],
        )
        records, stats = build_gold_records(zenodo_root)
        assert len(records) == 3
        assert "human" in stats["unlabeled"]
        assert "301" in stats["unlabeled"]["human"][0]

    def test_missing_file_points_at_the_path(self, tmp_path):
        with pytest.raises(DataValidationError) as excinfo:
            build_gold_records(tmp_path)
        assert "Zenodo file not found" in str(excinfo.value)

    def test_missing_column_lists_available_columns(self, zenodo_root):
        broken = zenodo_root / "llm_analysis" / "input" / "sampled_human_review.csv"
        _write_csv(broken, ["Comment_URL", "Body"], [{"Comment_URL": "u", "Body": "b"}])
        with pytest.raises(DataValidationError) as excinfo:
            build_gold_records(zenodo_root)
        message = str(excinfo.value)
        assert "missing expected column" in message
        assert "Available columns" in message

    def test_missing_root_is_an_error(self, tmp_path):
        with pytest.raises(DataValidationError):
            build_gold_records(tmp_path / "nope")


class TestOutput:
    def test_jsonl_round_trips_through_the_loader(self, zenodo_root, tmp_path):
        records, _ = build_gold_records(zenodo_root)
        target = write_jsonl(records, tmp_path / "out" / "gold.jsonl")
        assert target.is_file()

        loaded = load_dataset(target, "auto")
        assert len(loaded) == 4
        assert {r.gold_label for r in loaded} == {
            "None",
            "General",
            "Valid-Fully",
            "Valid-Unaddressed",
        }
        assert {r.source for r in loaded} == {"file-level", "hunk-level", "human"}

    def test_provenance_is_written(self, zenodo_root, tmp_path):
        _, stats = build_gold_records(zenodo_root)
        target = write_provenance(stats, tmp_path / "gold.jsonl.provenance.json")
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
        assert payload["count"] == 4
        assert payload["label_codes"]["2,2"] == 1
