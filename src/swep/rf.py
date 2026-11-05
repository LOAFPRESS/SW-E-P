"""Stratified 5-fold Random Forest experiment for RQ3 (member C).

The protocol mirrors the paper's appendix
(``address_feature_matrix/analyze_feature_importance_with_rf.py``):

* ``StratifiedKFold(n_splits=5, shuffle=True, random_state=42)``;
* ``RandomForestClassifier(random_state=42)`` with the scikit-learn defaults;
* accuracy and macro-F1 per fold, averaged over folds;
* one feature matrix for all folds (built once, before splitting).

scikit-learn is imported lazily so that the annotation pipeline keeps working in
environments without it (the mock provider path only needs pandas and PyYAML).
"""

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

DEFAULT_N_SPLITS = 5
DEFAULT_RANDOM_STATE = 42


class FoldResult(object):
    """Metrics for one cross-validation fold."""

    def __init__(self, fold: int, n_train: int, n_test: int, accuracy: float, macro_f1: float, y_true: np.ndarray, y_pred: np.ndarray):
        self.fold = fold
        self.n_train = n_train
        self.n_test = n_test
        self.accuracy = accuracy
        self.macro_f1 = macro_f1
        self.y_true = y_true
        self.y_pred = y_pred

    def as_dict(self) -> Dict[str, object]:
        return {
            "fold": self.fold,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "predicted_positive": int(self.y_pred.sum()),
            "actual_positive": int(self.y_true.sum()),
        }


class CVResult(object):
    """Aggregated outcome of the stratified 5-fold run."""

    def __init__(self, folds: List[FoldResult], feature_names: Sequence[str], random_state: int, n_splits: int):
        self.folds = folds
        self.feature_names = list(feature_names)
        self.random_state = random_state
        self.n_splits = n_splits

    @property
    def accuracy(self) -> float:
        return float(np.mean([fold.accuracy for fold in self.folds])) if self.folds else 0.0

    @property
    def accuracy_std(self) -> float:
        return float(np.std([fold.accuracy for fold in self.folds])) if self.folds else 0.0

    @property
    def macro_f1(self) -> float:
        return float(np.mean([fold.macro_f1 for fold in self.folds])) if self.folds else 0.0

    @property
    def macro_f1_std(self) -> float:
        return float(np.std([fold.macro_f1 for fold in self.folds])) if self.folds else 0.0

    def out_of_fold(self) -> Dict[str, np.ndarray]:
        """Concatenated held-out predictions, one pair per sample."""
        if not self.folds:
            return {"y_true": np.array([]), "y_pred": np.array([])}
        return {
            "y_true": np.concatenate([fold.y_true for fold in self.folds]),
            "y_pred": np.concatenate([fold.y_pred for fold in self.folds]),
        }

    def summary(self) -> Dict[str, object]:
        out_of_fold = self.out_of_fold()
        counts = np.bincount(out_of_fold["y_pred"].astype(int), minlength=2) if out_of_fold["y_pred"].size else np.zeros(2, dtype=int)
        return {
            "n_splits": self.n_splits,
            "random_state": self.random_state,
            "n_samples": int(out_of_fold["y_true"].size),
            "n_features": len(self.feature_names),
            "accuracy_mean": round(self.accuracy, 4),
            "accuracy_std": round(self.accuracy_std, 4),
            "macro_f1_mean": round(self.macro_f1, 4),
            "macro_f1_std": round(self.macro_f1_std, 4),
            "predicted_distribution": {"not_addressed": int(counts[0]), "addressed": int(counts[1])},
            "folds": [fold.as_dict() for fold in self.folds],
        }


def _make_classifier(random_state: int = DEFAULT_RANDOM_STATE, n_estimators: Optional[int] = None, class_weight: Optional[str] = None, max_depth: Optional[int] = None):
    from sklearn.ensemble import RandomForestClassifier

    kwargs = {"random_state": random_state}
    if n_estimators is not None:
        kwargs["n_estimators"] = n_estimators
    if class_weight is not None:
        kwargs["class_weight"] = class_weight
    if max_depth is not None:
        kwargs["max_depth"] = max_depth
    return RandomForestClassifier(**kwargs)


def cross_validate(
    X: pd.DataFrame,
    y: Sequence[int],
    n_splits: int = DEFAULT_N_SPLITS,
    random_state: int = DEFAULT_RANDOM_STATE,
    n_estimators: Optional[int] = None,
    class_weight: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> CVResult:
    """Run stratified k-fold CV and return per-fold and averaged metrics."""
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import StratifiedKFold

    labels = np.asarray(y).astype(int)
    if X.shape[0] != labels.shape[0]:
        raise ValueError("X has %d rows but y has %d" % (X.shape[0], labels.shape[0]))
    if len(np.unique(labels)) < 2:
        raise ValueError("the label vector contains a single class; a classifier cannot be evaluated")

    values = X.values.astype(np.float64)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    folds: List[FoldResult] = []
    for index, (train_index, test_index) in enumerate(splitter.split(values, labels), start=1):
        model = _make_classifier(random_state=random_state, n_estimators=n_estimators, class_weight=class_weight, max_depth=max_depth)
        model.fit(values[train_index], labels[train_index])
        predicted = model.predict(values[test_index])
        folds.append(
            FoldResult(
                fold=index,
                n_train=int(train_index.size),
                n_test=int(test_index.size),
                accuracy=float(accuracy_score(labels[test_index], predicted)),
                macro_f1=float(f1_score(labels[test_index], predicted, average="macro")),
                y_true=labels[test_index],
                y_pred=np.asarray(predicted),
            )
        )
    return CVResult(folds=folds, feature_names=list(X.columns), random_state=random_state, n_splits=n_splits)


def fit_full(
    X: pd.DataFrame,
    y: Sequence[int],
    random_state: int = DEFAULT_RANDOM_STATE,
    n_estimators: Optional[int] = None,
    class_weight: Optional[str] = None,
    max_depth: Optional[int] = None,
):
    """Fit one forest on the whole matrix (used for impurity-based importances)."""
    model = _make_classifier(random_state=random_state, n_estimators=n_estimators, class_weight=class_weight, max_depth=max_depth)
    model.fit(X.values.astype(np.float64), np.asarray(y).astype(int))
    return model


def impurity_importance(feature_names: Sequence[str], model) -> pd.DataFrame:
    """Mean decrease in impurity, sorted descending."""
    values = np.asarray(model.feature_importances_, dtype=float)
    frame = pd.DataFrame({"feature": list(feature_names), "mean_decrease_impurity": values})
    return frame.sort_values("mean_decrease_impurity", ascending=False).reset_index(drop=True)
