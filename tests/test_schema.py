"""Tests for the shared schema: labels, records and the CSV contract."""

import pytest

from swep.errors import DataValidationError
from swep.schema import (
    ADDRESSED_LABELS,
    CSV_COLUMNS,
    SIX_CLASS_LABELS,
    AnnotationRecord,
    ReviewRecord,
    Stage1Label,
    Stage2Label,
    final_label_for,
)


class TestLabelCoercion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Valid", Stage1Label.VALID),
            ("valid", Stage1Label.VALID),
            (" VALID ", Stage1Label.VALID),
            ("Valid-Fully", Stage1Label.VALID),
            ("General", Stage1Label.GENERAL),
            ("None", Stage1Label.NONE),
        ],
    )
    def test_stage1_accepts_common_spellings(self, raw, expected):
        assert Stage1Label.coerce(raw) is expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Valid-Fully", Stage2Label.FULLY),
            ("valid_fully", Stage2Label.FULLY),
            ("Valid-Fully ", Stage2Label.FULLY),
            ("Valid-Partially", Stage2Label.PARTIALLY),
            ("Valid-Unaddressed", Stage2Label.UNADDRESSED),
            ("Valid-Uncertain", Stage2Label.UNCERTAIN),
            ("not addressed", Stage2Label.UNADDRESSED),
            ("uncertain", Stage2Label.UNCERTAIN),
        ],
    )
    def test_stage2_accepts_aliases(self, raw, expected):
        assert Stage2Label.coerce(raw) is expected

    def test_unknown_label_is_rejected_with_a_useful_message(self):
        with pytest.raises(ValueError) as excinfo:
            Stage1Label.coerce("Maybe")
        assert "Maybe" in str(excinfo.value)
        assert "Valid" in str(excinfo.value)

    def test_empty_label_is_rejected(self):
        with pytest.raises(ValueError):
            Stage2Label.coerce("")


class TestFinalLabel:
    def test_non_valid_comments_keep_the_stage1_label(self):
        assert final_label_for("None", "") == "None"
        assert final_label_for("General", None) == "General"

    def test_valid_comments_use_the_stage2_label(self):
        assert final_label_for("Valid", "Valid-Fully") == "Valid-Fully"

    def test_valid_without_stage2_is_flagged(self):
        label = final_label_for("Valid", "")
        assert label.startswith("Valid")
        assert label in SIX_CLASS_LABELS

    def test_unexpected_combination_is_reported(self):
        with pytest.raises(ValueError):
            final_label_for("Valid", "None")


class TestReviewRecord:
    def test_validate_accepts_a_complete_record(self):
        record = ReviewRecord(comment_id="c1", source="human", comment_text="fix this")
        record.validate()

    @pytest.mark.parametrize("field", ["comment_id", "source", "comment_text"])
    def test_validate_names_the_missing_field(self, field):
        values = {"comment_id": "c1", "source": "human", "comment_text": "fix this"}
        values[field] = ""
        record = ReviewRecord(**values)
        with pytest.raises(DataValidationError) as excinfo:
            record.validate()
        assert field in str(excinfo.value)


class TestAnnotationRecord:
    def _record(self, **overrides):
        values = {
            "comment_id": "c1",
            "source": "human",
            "stage1_label": "Valid",
            "stage2_label": "Valid-Fully",
            "final_label": "Valid-Fully",
            "stage1_issues": ["close the handle"],
            "model_stage1": "gpt-4.1",
            "model_stage2": "o3-mini",
            "prompt_version": "v1",
        }
        values.update(overrides)
        return AnnotationRecord(**values)

    def test_row_contains_every_csv_column_in_order(self):
        row = self._record().to_row()
        assert list(row.keys()) == list(CSV_COLUMNS)
        assert len(CSV_COLUMNS) == 21

    def test_lists_are_serialised_deterministically(self):
        row = self._record(stage1_issues=["b", "a"]).to_row()
        assert row["stage1_issues"] == "b | a"

    def test_addressed_flag_covers_the_expected_labels(self):
        for label in ADDRESSED_LABELS:
            assert self._record(stage2_label=label, final_label=label).is_addressed is True
        for label in ("None", "General", "Valid-Unaddressed"):
            assert self._record(stage2_label=label, final_label=label).is_addressed is False

    def test_error_rows_are_marked_as_not_addressed(self):
        row = self._record(error="boom").to_row()
        assert row["error"] == "boom"
        assert row["is_addressed"] == 0
