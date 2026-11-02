"""Label distribution and accuracy metrics, implemented without scikit-learn.

Member C owns the Random Forest and SHAP analysis, and Member A owns the final
evaluation; this module only provides the two sanity checks the annotation stage
needs on its own:

* the label distribution of a run (does the model over-predict ``Valid``?), and
* accuracy / macro-F1 against the gold labels, comparable to the numbers the
  paper reports in Table VII (6-class OA 86.1%, macro-F1 74.6%).

Every metric here is computed from plain dictionaries so that the annotation
module keeps working even in an environment where scikit-learn is absent.
"""

from typing import Dict, List, Sequence

from .schema import ADDRESSED_LABELS, SIX_CLASS_LABELS


def label_distribution(labels: Sequence[str], order: Sequence[str] = None) -> Dict[str, int]:
    """Count occurrences of each label, restricted to ``order`` when given."""
    counts: Dict[str, int] = {}
    for label in labels:
        key = label or "(empty)"
        counts[key] = counts.get(key, 0) + 1
    if order:
        return {label: counts.get(label, 0) for label in order}
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for truth, pred in zip(y_true, y_pred) if truth == pred)
    return correct / float(len(y_true))


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] = None) -> float:
    """Unweighted mean of per-class F1 over ``labels`` (default: observed)."""
    labels = list(labels or sorted(set(y_true) | set(y_pred)))
    if not labels:
        return 0.0
    scores = []
    for label in labels:
        tp = sum(1 for truth, pred in zip(y_true, y_pred) if truth == label and pred == label)
        fp = sum(1 for truth, pred in zip(y_true, y_pred) if truth != label and pred == label)
        fn = sum(1 for truth, pred in zip(y_true, y_pred) if truth == label and pred != label)
        precision = tp / float(tp + fp) if tp + fp else 0.0
        recall = tp / float(tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(f1)
    return sum(scores) / float(len(scores))


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] = None) -> List[List[int]]:
    """Row = gold label, column = predicted label."""
    labels = list(labels or SIX_CLASS_LABELS)
    index = {label: position for position, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for truth, pred in zip(y_true, y_pred):
        if truth in index and pred in index:
            matrix[index[truth]][index[pred]] += 1
    return matrix


def classification_report(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] = None) -> Dict[str, object]:
    """Accuracy, macro-F1, per-class F1 and the confusion matrix."""
    labels = list(labels or SIX_CLASS_LABELS)
    per_class = {}
    for label in labels:
        tp = sum(1 for truth, pred in zip(y_true, y_pred) if truth == label and pred == label)
        fp = sum(1 for truth, pred in zip(y_true, y_pred) if truth != label and pred == label)
        fn = sum(1 for truth, pred in zip(y_true, y_pred) if truth == label and pred != label)
        precision = tp / float(tp + fp) if tp + fp else 0.0
        recall = tp / float(tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "support": sum(1 for truth in y_true if truth == label),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return {
        "n": len(y_true),
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "macro_f1": round(macro_f1(y_true, y_pred, labels), 4),
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": confusion_matrix(y_true, y_pred, labels)},
    }


def to_binary(label: str) -> str:
    """Collapse the six classes into the binary Addressed / Not-Addressed view."""
    return "Addressed" if label in ADDRESSED_LABELS else "Not-Addressed"


def binary_report(y_true: Sequence[str], y_pred: Sequence[str]) -> Dict[str, object]:
    """Binary accuracy/F1, matching the paper's 91.5% / 89.8% row."""
    truth = [to_binary(label) for label in y_true]
    pred = [to_binary(label) for label in y_pred]
    labels = ["Addressed", "Not-Addressed"]
    return classification_report(truth, pred, labels)
