"""Tests for the SHAP wrapper."""

import os

import numpy as np
import pandas as pd
import pytest

from swep.explain import _positive_class, explain_with_cv, write_bar_plot, write_summary_plot


def separable(n_per_class=15, n_features=4):
    rng = np.random.RandomState(3)
    X = rng.normal(size=(2 * n_per_class, n_features))
    y = np.array([0] * n_per_class + [1] * n_per_class)
    X[y == 1] += 3.0
    names = ["Text_Length", "Repo_Total_File_Size", "Is_Human", "LDA_Topic_Prob_0"][:n_features]
    frame = pd.DataFrame(X, columns=names)
    return frame, y


class TestPositiveClass(object):
    def test_list_returns_the_positive_class(self):
        values = [np.zeros((2, 3)), np.ones((2, 3))]
        picked = _positive_class(values)
        assert picked.shape == (2, 3)
        assert picked.sum() == 6.0

    def test_three_dimensional_array_uses_the_last_class(self):
        array = np.zeros((2, 3, 2))
        array[:, :, 1] = 5.0
        picked = _positive_class(array)
        assert picked.shape == (2, 3)
        assert np.all(picked == 5.0)

    def test_two_dimensional_array_is_returned_as_is(self):
        array = np.arange(6, dtype=float).reshape(2, 3)
        assert np.array_equal(_positive_class(array), array)


class TestExplain(object):
    def test_values_cover_every_held_out_row(self):
        X, y = separable()
        result = explain_with_cv(X, y, n_splits=3, random_state=42)
        table = result["table"]
        assert table.values.shape == (len(X), X.shape[1])
        assert table.samples.shape == (len(X), X.shape[1])
        assert len(result["models"]) == 3

    def test_importance_frame_is_ranked(self):
        X, y = separable()
        table = explain_with_cv(X, y, n_splits=3, random_state=42)["table"]
        frame = table.importance_frame()
        assert list(frame.columns) == ["feature", "mean_abs_shap", "mean_shap", "rank"]
        assert frame["mean_abs_shap"].is_monotonic_decreasing
        assert frame["rank"].tolist() == [1, 2, 3, 4]

    def test_group_frame_is_present(self):
        X, y = separable()
        groups = explain_with_cv(X, y, n_splits=3, random_state=42)["table"].group_frame()
        assert not groups.empty
        assert groups["sum_abs_shap"].is_monotonic_decreasing

    def test_top_features(self):
        X, y = separable()
        table = explain_with_cv(X, y, n_splits=3, random_state=42)["table"]
        assert len(table.top_features(2)) == 2


class TestPlots(object):
    def test_summary_and_bar_plots_are_written(self, tmp_path):
        X, y = separable()
        table = explain_with_cv(X, y, n_splits=3, random_state=42)["table"]
        summary = os.path.join(str(tmp_path), "summary.png")
        bar = os.path.join(str(tmp_path), "bar.png")
        assert write_summary_plot(table, summary) == summary
        assert write_bar_plot(table, bar) == bar
        assert os.path.getsize(summary) > 1000
        assert os.path.getsize(bar) > 1000
