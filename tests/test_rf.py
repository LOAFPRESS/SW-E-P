"""Tests for the stratified 5-fold Random Forest helper."""

import numpy as np
import pandas as pd
import pytest

from swep.rf import cross_validate, fit_full, impurity_importance


def separable(n_per_class=20, n_features=4):
    """A deterministic, linearly separable two-class dataset."""
    rng = np.random.RandomState(0)
    X = rng.normal(size=(2 * n_per_class, n_features))
    y = np.array([0] * n_per_class + [1] * n_per_class)
    X[y == 1] += 3.0
    frame = pd.DataFrame(X, columns=["f%d" % index for index in range(n_features)])
    frame["label"] = y
    return frame.drop(columns=["label"]), y


class TestCrossValidate(object):
    def test_returns_one_result_per_fold(self):
        X, y = separable()
        result = cross_validate(X, y, n_splits=3, n_estimators=20)
        assert len(result.folds) == 3
        assert [fold.fold for fold in result.folds] == [1, 2, 3]
        assert result.feature_names == list(X.columns)
        assert result.n_splits == 3

    def test_separable_data_is_classified_well(self):
        X, y = separable()
        result = cross_validate(X, y, n_splits=3, n_estimators=50)
        assert result.accuracy > 0.9
        assert result.macro_f1 > 0.9

    def test_summary_shape(self):
        X, y = separable()
        summary = cross_validate(X, y, n_splits=3, n_estimators=10).summary()
        assert summary["n_samples"] == len(y)
        assert summary["n_features"] == X.shape[1]
        assert 0.0 <= summary["accuracy_mean"] <= 1.0
        assert len(summary["folds"]) == 3
        assert summary["predicted_distribution"]["addressed"] + summary["predicted_distribution"]["not_addressed"] == len(y)

    def test_out_of_fold_predictions_cover_every_row(self):
        X, y = separable()
        out_of_fold = cross_validate(X, y, n_splits=4, n_estimators=10).out_of_fold()
        assert sorted(out_of_fold["y_true"].tolist()) == sorted(y.tolist())
        assert out_of_fold["y_pred"].shape == out_of_fold["y_true"].shape

    def test_single_class_is_rejected(self):
        X, _ = separable()
        with pytest.raises(ValueError, match="single class"):
            cross_validate(X, np.zeros(len(X)), n_splits=3)

    def test_row_mismatch_is_rejected(self):
        X, y = separable()
        with pytest.raises(ValueError, match="rows"):
            cross_validate(X, y[:-1], n_splits=3)

    def test_random_state_is_reproducible(self):
        X, y = separable()
        first = cross_validate(X, y, n_splits=3, n_estimators=10).accuracy
        second = cross_validate(X, y, n_splits=3, n_estimators=10).accuracy
        assert first == pytest.approx(second)


class TestFullModel(object):
    def test_impurity_importance_is_ranked(self):
        X, y = separable()
        model = fit_full(X, y, n_estimators=30)
        frame = impurity_importance(X.columns, model)
        assert list(frame.columns) == ["feature", "mean_decrease_impurity"]
        assert frame["mean_decrease_impurity"].is_monotonic_decreasing
        assert pytest.approx(float(frame["mean_decrease_impurity"].sum()), abs=1e-6) == 1.0
