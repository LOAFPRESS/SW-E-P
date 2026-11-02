"""Tests for the label-distribution and accuracy helpers."""

import pytest

from swep.metrics import (
    accuracy,
    binary_report,
    classification_report,
    confusion_matrix,
    label_distribution,
    macro_f1,
    to_binary,
)
from swep.schema import SIX_CLASS_LABELS


class TestDistribution:
    def test_counts_and_order(self):
        counts = label_distribution(["Valid-Fully", "None", "Valid-Fully"], ["None", "Valid-Fully"])
        assert counts == {"None": 1, "Valid-Fully": 2}

    def test_empty_labels_bucket(self):
        assert label_distribution(["", ""]) == {"(empty)": 2}


class TestAccuracy:
    def test_perfect(self):
        assert accuracy(["a", "b"], ["a", "b"]) == 1.0

    def test_half(self):
        assert accuracy(["a", "b"], ["a", "a"]) == 0.5

    def test_empty_is_zero(self):
        assert accuracy([], []) == 0.0


class TestMacroF1:
    def test_perfect(self):
        labels = ["None", "General"]
        assert macro_f1(["None", "General"], ["None", "General"], labels) == pytest.approx(1.0)

    def test_one_missed_class_lowers_the_mean(self):
        labels = ["None", "General"]
        # "General" is never predicted: its F1 is 0 and it drags the mean down.
        # The wrong "None" prediction on the General row is a false positive for
        # "None", so that class scores F1 = 2*(1/2)*1/(1/2+1) = 2/3.
        score = macro_f1(["None", "General"], ["None", "None"], labels)
        assert score == pytest.approx(1.0 / 3.0)

    def test_single_class(self):
        assert macro_f1(["a", "a"], ["a", "a"], ["a"]) == pytest.approx(1.0)


class TestConfusionMatrix:
    def test_rows_are_gold_columns_are_predicted(self):
        matrix = confusion_matrix(["None", "General"], ["General", "General"], ["None", "General"])
        assert matrix[0][1] == 1  # None predicted as General
        assert matrix[1][1] == 1  # General predicted as General

    def test_unknown_labels_are_ignored(self):
        matrix = confusion_matrix(["None"], ["mystery"], ["None", "General"])
        assert sum(sum(row) for row in matrix) == 0


class TestReport:
    def test_six_class_report_shape(self):
        report = classification_report(
            ["None", "Valid-Fully"], ["None", "Valid-Fully"], SIX_CLASS_LABELS
        )
        assert report["n"] == 2
        assert report["accuracy"] == 1.0
        assert set(report["per_class"]) == set(SIX_CLASS_LABELS)
        assert report["confusion_matrix"]["labels"] == list(SIX_CLASS_LABELS)

    def test_binary_collapse(self):
        assert to_binary("Valid-Fully") == "Addressed"
        assert to_binary("Valid-Partially") == "Addressed"
        assert to_binary("Valid-Unaddressed") == "Not-Addressed"
        assert to_binary("None") == "Not-Addressed"

    def test_binary_report_matches_paper_style(self):
        report = binary_report(["Valid-Fully", "None"], ["Valid-Fully", "General"])
        assert report["accuracy"] == 1.0
        assert report["n"] == 2
