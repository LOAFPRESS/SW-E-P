"""SHAP explanations for the RQ3 Random Forest (member C).

The appendix computes SHAP values inside the cross-validation loop with
``shap.TreeExplainer(model, data=train_feature_arr,
feature_perturbation="interventional")``, keeps the positive-class matrix of
every fold, and concatenates the folds before drawing the summary plot.  This
module does the same, but returns tidy tables so the numbers can be written to
CSV and quoted in the report instead of only living in a PNG.
"""

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .features import group_importance


class ShapTable(object):
    """Global SHAP importances collected over the cross-validation folds."""

    def __init__(self, feature_names: Sequence[str], values: np.ndarray, samples: np.ndarray):
        self.feature_names = list(feature_names)
        self.values = values
        self.samples = samples

    @property
    def mean_abs(self) -> np.ndarray:
        return np.abs(self.values).mean(axis=0)

    @property
    def signed_mean(self) -> np.ndarray:
        return self.values.mean(axis=0)

    def importance_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "feature": self.feature_names,
                "mean_abs_shap": self.mean_abs,
                "mean_shap": self.signed_mean,
            }
        )
        frame = frame.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
        frame["rank"] = np.arange(1, frame.shape[0] + 1)
        return frame

    def group_frame(self) -> pd.DataFrame:
        return group_importance(self.feature_names, self.mean_abs)

    def top_features(self, limit: int = 10) -> List[str]:
        frame = self.importance_frame()
        return list(frame["feature"].head(limit))


def _positive_class(values):
    """Pick the positive-class matrix from whatever shape the SHAP API returns."""
    if isinstance(values, list):
        return np.asarray(values[1] if len(values) > 1 else values[0], dtype=float)
    array = np.asarray(values, dtype=float)
    if array.ndim == 3:
        # (samples, features, classes) in newer versions
        return array[:, :, 1]
    return array


def explain_folds(
    fold_models: Sequence[object],
    fold_matrices: Sequence[np.ndarray],
    fold_backgrounds: Sequence[np.ndarray],
    feature_names: Sequence[str],
) -> ShapTable:
    """Compute interventional TreeSHAP for each fold and concatenate them."""
    import shap

    values_parts = []
    sample_parts = []
    for model, matrix, background in zip(fold_models, fold_matrices, fold_backgrounds):
        explainer = shap.TreeExplainer(model, data=background, feature_perturbation="interventional")
        values_parts.append(_positive_class(explainer.shap_values(matrix, check_additivity=False)))
        sample_parts.append(np.asarray(matrix, dtype=np.float64))
    return ShapTable(feature_names, np.vstack(values_parts), np.vstack(sample_parts))


def explain_with_cv(X: pd.DataFrame, y: Sequence[int], n_splits: int = 5, random_state: int = 42) -> Dict[str, object]:
    """Run the folds once more, keeping (model, test matrix, train matrix) for SHAP.

    Returns a dict with the :class:`ShapTable` plus the per-fold models so callers
    can also inspect splits.
    """
    from sklearn.model_selection import StratifiedKFold

    from .rf import _make_classifier

    values = X.values.astype(np.float64)
    labels = np.asarray(y).astype(int)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)

    models = []
    matrices = []
    backgrounds = []
    folds = []
    for index, (train_index, test_index) in enumerate(splitter.split(values, labels), start=1):
        model = _make_classifier(random_state=random_state)
        model.fit(values[train_index], labels[train_index])
        models.append(model)
        matrices.append(values[test_index])
        backgrounds.append(values[train_index])
        folds.append(index)

    table = explain_folds(models, matrices, backgrounds, list(X.columns))
    return {"table": table, "models": models, "folds": folds}


def write_summary_plot(table: ShapTable, path: str, max_display: Optional[int] = 20) -> str:
    """Save the beeswarm summary plot (the appendix figure)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap

    figure = plt.figure()
    try:
        shap.summary_plot(table.values, table.samples, feature_names=table.feature_names, max_display=max_display, show=False)
        figure.savefig(path, bbox_inches="tight", dpi=150)
    finally:
        plt.close(figure)
    return path


def write_bar_plot(table: ShapTable, path: str, max_display: int = 20) -> str:
    """Save the mean absolute SHAP bar plot."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap

    figure = plt.figure()
    try:
        shap.summary_plot(table.values, table.samples, feature_names=table.feature_names, plot_type="bar", max_display=max_display, show=False)
        figure.savefig(path, bbox_inches="tight", dpi=150)
    finally:
        plt.close(figure)
    return path
