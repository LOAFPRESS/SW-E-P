"""RQ3 experiment driver: label loading, Random Forest, SHAP, artefacts.

The data comes from the Zenodo package's ``address_feature_matrix`` directory:

* ``_selected_reviews_with_features/reviews_contains_valid_by_LLM_lda_topics_selected.csv``
  (3879 reviews x 36-ish columns, the AutoSpearman-selected set);
* ``labels/all_reviews_with_LLM_labels.csv`` (``Comment_ID``, ``Change_Label``).

``Change_Label`` is 1 when the review was classified Valid and its addressed
status is ``2,1`` / ``2,2`` (see ``shape_labels_and_feature_under_LLM.py``), so
the positive class means "the review was acted upon".
"""

import json
import os
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .features import FeatureMatrix, build_feature_matrix

DEFAULT_FEATURES_REL = os.path.join("_selected_reviews_with_features", "reviews_contains_valid_by_LLM_lda_topics_selected.csv")
DEFAULT_LABELS_REL = os.path.join("labels", "all_reviews_with_LLM_labels.csv")
LABEL_COLUMN = "Change_Label"


def load_rq3_frame(
    root: str,
    features_path: Optional[str] = None,
    labels_path: Optional[str] = None,
) -> tuple:
    """Merge the feature matrix with the binary labels and describe the data."""
    features_path = features_path or os.path.join(root, DEFAULT_FEATURES_REL)
    labels_path = labels_path or os.path.join(root, DEFAULT_LABELS_REL)
    for path in (features_path, labels_path):
        if not os.path.exists(path):
            raise FileNotFoundError("RQ3 input not found: %s" % path)

    features = pd.read_csv(features_path)
    labels = pd.read_csv(labels_path)
    if "Comment_ID" not in features.columns:
        raise ValueError("the feature table needs a Comment_ID column, found: %s" % ", ".join(features.columns[:8]))
    if not {"Comment_ID", LABEL_COLUMN} <= set(labels.columns):
        raise ValueError("the label table needs Comment_ID and %s, found: %s" % (LABEL_COLUMN, ", ".join(labels.columns)))

    before = len(features)
    frame = pd.merge(features, labels[["Comment_ID", LABEL_COLUMN]], on="Comment_ID", how="inner")
    if LABEL_COLUMN not in frame.columns:
        raise ValueError("%s missing after the merge" % LABEL_COLUMN)

    frame[LABEL_COLUMN] = pd.to_numeric(frame[LABEL_COLUMN], errors="coerce")
    unlabeled = int(frame[LABEL_COLUMN].isna().sum())
    frame = frame[frame[LABEL_COLUMN].notna()].copy()
    frame[LABEL_COLUMN] = frame[LABEL_COLUMN].astype(int)
    unexpected = sorted(set(frame[LABEL_COLUMN].unique()) - {0, 1})
    if unexpected:
        raise ValueError("unexpected %s value(s): %s" % (LABEL_COLUMN, unexpected))

    duplicates = int(frame["Comment_ID"].duplicated().sum())
    if duplicates:
        frame = frame.drop_duplicates(subset=["Comment_ID"]).reset_index(drop=True)

    meta = {
        "features_path": features_path,
        "labels_path": labels_path,
        "rows_before_merge": int(before),
        "rows_after_merge": int(len(frame)),
        "unlabeled_rows_dropped": unlabeled,
        "duplicate_rows_dropped": duplicates,
        "positive": int(frame[LABEL_COLUMN].sum()),
        "negative": int(len(frame) - frame[LABEL_COLUMN].sum()),
        "positive_rate": round(float(frame[LABEL_COLUMN].mean()), 4),
        "by_source": {str(name): int(count) for name, count in frame["Source"].value_counts().items()} if "Source" in frame.columns else {},
    }
    return frame, meta


def run_experiment(
    frame: pd.DataFrame,
    groups: Optional[Sequence[str]] = None,
    action_binary: Optional[bool] = None,
    n_splits: int = 5,
    random_state: int = 42,
    ai_only: bool = False,
    explain: bool = True,
    n_estimators: Optional[int] = None,
) -> Dict[str, object]:
    """Build features, run the CV, and optionally the SHAP analysis."""
    from . import explain as explain_module
    from . import rf

    data = frame
    if ai_only:
        if "Source" not in data.columns:
            raise ValueError("ai_only=True needs a Source column")
        data = data[data["Source"].astype(str) != "Human"].reset_index(drop=True)

    matrix: FeatureMatrix = build_feature_matrix(data, groups=groups, action_binary=action_binary)
    if ai_only and "Is_Human" in matrix.frame.columns:
        # The appendix drops Is_Human in the AI-only variant: the column is
        # constant there and would only add a zero-importance feature.
        matrix = matrix.drop_columns(["Is_Human"])
        matrix.notes.append("Is_Human dropped: the AI-only variant keeps a single source family")
    X = matrix.frame
    y = data[LABEL_COLUMN].astype(int).values

    cv = rf.cross_validate(X, y, n_splits=n_splits, random_state=random_state, n_estimators=n_estimators)
    report: Dict[str, object] = {
        "mode": "ai_only" if ai_only else "all_reviews",
        "rows": int(X.shape[0]),
        "feature_matrix": matrix.describe(),
        "cross_validation": cv.summary(),
    }

    if describe_shap := explain:
        try:
            shap_result = explain_module.explain_with_cv(X, y, n_splits=n_splits, random_state=random_state)
            table = shap_result["table"]
            report["shap"] = {
                "available": True,
                "importance": table.importance_frame().to_dict(orient="records"),
                "groups": table.group_frame().to_dict(orient="records"),
                "top_features": table.top_features(10),
            }
            report["_shap_table"] = table
        except Exception as error:  # pragma: no cover - depends on the shap build
            report["shap"] = {"available": False, "error": "%s: %s" % (type(error).__name__, error)}
    return report


def write_report(report: Dict[str, object], output_dir: str, dataset_meta: Optional[Dict[str, object]] = None, plot: bool = True) -> List[str]:
    """Persist the experiment as JSON/CSV/Markdown artefacts; returns the paths."""
    os.makedirs(output_dir, exist_ok=True)
    written: List[str] = []

    shap_table = report.pop("_shap_table", None)
    payload = dict(report)
    if dataset_meta is not None:
        payload["dataset"] = dataset_meta

    metrics_path = os.path.join(output_dir, "rq3_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    written.append(metrics_path)

    shap_info = payload.get("shap") or {}
    if shap_info.get("available"):
        importance = pd.DataFrame(shap_info["importance"])
        path = os.path.join(output_dir, "rq3_feature_importance.csv")
        importance.to_csv(path, index=False, encoding="utf-8")
        written.append(path)

        groups = pd.DataFrame(shap_info["groups"])
        path = os.path.join(output_dir, "rq3_group_importance.csv")
        groups.to_csv(path, index=False, encoding="utf-8")
        written.append(path)

        if plot and shap_table is not None:
            from .explain import write_bar_plot, write_summary_plot

            path = os.path.join(output_dir, "rq3_shap_summary.png")
            write_summary_plot(shap_table, path)
            written.append(path)
            path = os.path.join(output_dir, "rq3_shap_bar.png")
            write_bar_plot(shap_table, path)
            written.append(path)

    report_md = os.path.join(output_dir, "rq3_report.md")
    with open(report_md, "w", encoding="utf-8") as handle:
        handle.write(_render_markdown(payload))
    written.append(report_md)
    return written


def _render_markdown(payload: Dict[str, object]) -> str:
    cv = payload.get("cross_validation") or {}
    lines = ["# RQ3 Random Forest report", ""]
    lines.append("- mode: `%s`" % payload.get("mode"))
    lines.append("- rows: %s" % payload.get("rows"))
    lines.append("- features: %s" % cv.get("n_features"))
    lines.append("")
    lines.append("## Stratified 5-fold metrics")
    lines.append("")
    lines.append("| metric | mean | std |")
    lines.append("| --- | --- | --- |")
    lines.append("| accuracy | %.4f | %.4f |" % (cv.get("accuracy_mean", 0.0), cv.get("accuracy_std", 0.0)))
    lines.append("| macro F1 | %.4f | %.4f |" % (cv.get("macro_f1_mean", 0.0), cv.get("macro_f1_std", 0.0)))
    lines.append("")
    lines.append("| fold | n train | n test | accuracy | macro F1 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for fold in cv.get("folds", []):
        lines.append("| %d | %d | %d | %.4f | %.4f |" % (fold["fold"], fold["n_train"], fold["n_test"], fold["accuracy"], fold["macro_f1"]))
    lines.append("")

    shap_info = payload.get("shap") or {}
    if shap_info.get("available"):
        lines.append("## SHAP (positive class)")
        lines.append("")
        lines.append("| rank | feature | mean abs SHAP | mean SHAP |")
        lines.append("| --- | --- | --- | --- |")
        for index, row in enumerate(shap_info["importance"][:15], start=1):
            lines.append("| %d | %s | %.4f | %.4f |" % (index, row["feature"], row["mean_abs_shap"], row["mean_shap"]))
        lines.append("")
        lines.append("| group | mean abs SHAP | sum abs SHAP | features |")
        lines.append("| --- | --- | --- | --- |")
        for row in shap_info["groups"]:
            lines.append("| %s | %.4f | %.4f | %d |" % (row["group"], row["mean_abs_shap"], row["sum_abs_shap"], row["features"]))
        lines.append("")
    else:
        lines.append("SHAP unavailable: %s" % shap_info.get("error"))
        lines.append("")

    dataset = payload.get("dataset") or {}
    if dataset:
        lines.append("## Dataset")
        lines.append("")
        lines.append("- rows after merge: %s" % dataset.get("rows_after_merge"))
        lines.append("- positive rate: %s" % dataset.get("positive_rate"))
        lines.append("")

    missing = (payload.get("feature_matrix") or {}).get("missing") or {}
    if missing:
        lines.append("## Features that the input table does not provide")
        lines.append("")
        for key, values in missing.items():
            lines.append("- %s: %s" % (key, ", ".join(values)))
        lines.append("")
    return "\n".join(lines) + "\n"
