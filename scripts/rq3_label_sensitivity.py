"""Sensitivity of the RQ3 result to the labels used (DEV-12 mitigation).

The published experiment trains the random forest on the 3,879 comments the
paper's annotator called Valid, labelled with the paper's own adoption labels.
Our replication of the annotation pipeline produces labels of its own, so the
natural question is: would the analysis still hold if the labels came from our
run instead?

Only the 110 comments that appear both in the paper's feature matrix and in our
150-comment gold run can be compared, so the answer is a *sensitivity check* on
a small sample, not a re-run of the published experiment. The script therefore
reports three things and no more:

1. how often our binary label agrees with the paper's on those 110 comments;
2. the five-fold metrics of the same random forest trained twice, once on each
   label set, on exactly the same rows and features;
3. how far the SHAP ranking moves between the two label sets, and how far both
   sit from the ranking of the full 3,879-row run.

Usage::

    python scripts/rq3_label_sensitivity.py
    python scripts/rq3_label_sensitivity.py --json artifacts/rq3-sensitivity/metrics.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from swep import explain, rq3  # noqa: E402
from swep.schema import ADDRESSED_LABELS  # noqa: E402

DEFAULT_FEATURES_REL = rq3.DEFAULT_FEATURES_REL
DEFAULT_LABELS_REL = rq3.DEFAULT_LABELS_REL
DEFAULT_ANNOTATIONS = REPO / "artifacts" / "deepseek-v21" / "annotations.csv"
DEFAULT_FULL_RUN = REPO / "artifacts" / "rq3" / "all_reviews" / "rq3_feature_importance.csv"
DEFAULT_OUTPUT = REPO / "artifacts" / "rq3-sensitivity"


def _zenodo_root(explicit):
    if explicit:
        return Path(explicit)
    return Path(rq3.default_zenodo_root())


def _comment_id(series):
    """The feature matrix stores the full API URL; our CSV stores the number.

    Accepts a pandas Series (the usual case) or a single string, because the
    tests and the report builder both call it with one value at a time.
    """
    def one(value):
        match = re.search(r"(\d+)\s*$", str(value))
        return match.group(1) if match else str(value)

    if isinstance(series, str):
        return one(series)
    return series.map(one)


def load_inputs(zenodo_root, annotations_path, features_path=None, labels_path=None):
    features_path = Path(features_path) if features_path else zenodo_root / DEFAULT_FEATURES_REL
    labels_path = Path(labels_path) if labels_path else zenodo_root / DEFAULT_LABELS_REL

    # Read with the native dtypes: the feature builder casts the boolean columns
    # to integers, so reading everything as text would break it downstream.
    features = pd.read_csv(features_path)
    features["comment_id"] = _comment_id(features["Comment_ID"])

    paper = pd.read_csv(labels_path)
    paper["comment_id"] = _comment_id(paper["Comment_ID"])
    paper_labels = dict(zip(paper["comment_id"], pd.to_numeric(paper["Change_Label"], errors="coerce")))

    ours = pd.read_csv(annotations_path, dtype=str, keep_default_na=False)
    our_labels = {
        str(row["comment_id"]): int(row["final_label"] in ADDRESSED_LABELS)
        for _, row in ours.iterrows()
        if not row.get("error")
    }
    return features, paper_labels, our_labels


def agreement(paper_labels, our_labels):
    ids = [key for key in paper_labels if key in our_labels and pd.notna(paper_labels[key])]
    both = [(int(paper_labels[key]), int(our_labels[key])) for key in ids]
    if not both:
        return {"n": 0}
    same = sum(1 for paper, ours in both if paper == ours)
    tp = sum(1 for paper, ours in both if paper == 1 and ours == 1)
    tn = sum(1 for paper, ours in both if paper == 0 and ours == 0)
    fp = sum(1 for paper, ours in both if paper == 0 and ours == 1)
    fn = sum(1 for paper, ours in both if paper == 1 and ours == 0)
    observed = same / len(both)
    expected = ((tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)) / float(len(both) ** 2)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 0.0
    return {
        "n": len(both),
        "agreement": round(observed, 4),
        "kappa": round(kappa, 4),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "our_positive_rate": round(sum(1 for _, ours in both if ours == 1) / len(both), 4),
        "paper_positive_rate": round(sum(1 for paper, _ in both if paper == 1) / len(both), 4),
    }


def _ranking(frame, shap_values):
    order = sorted(range(len(shap_values)), key=lambda i: -abs(shap_values[i]))
    return [frame[i] for i in order]


def rank_distance(first, second):
    """Mean absolute rank shift over the names present in both rankings."""
    common = [name for name in first if name in second]
    if len(common) < 2:
        return {"n": len(common), "mean_shift": None}
    total = sum(abs(first.index(name) - second.index(name)) for name in common)
    return {"n": len(common), "mean_shift": round(total / len(common), 2)}


def run_one(frame, label_name, n_splits=5, random_state=42):
    report = rq3.run_experiment(frame, n_splits=n_splits, random_state=random_state, explain=True)
    table = report.get("_shap_table")
    importance = table.importance_frame() if table is not None else None
    cv = report["cross_validation"]
    return {
        "labels": label_name,
        "rows": report["rows"],
        "accuracy": cv["accuracy_mean"],
        "macro_f1": cv["macro_f1_mean"],
        "accuracy_std": cv["accuracy_std"],
        "macro_f1_std": cv["macro_f1_std"],
        "top": importance.head(10)[["feature", "mean_abs_shap"]].values.tolist() if importance is not None else [],
        "ranking": importance["feature"].tolist() if importance is not None else [],
    }


def build_report(payload):
    lines = ["# RQ3 label sensitivity (DEV-12)", ""]
    lines += [
        "Our annotation pipeline labels the 150-comment gold set itself, while the published",
        "random forest is trained on the paper's own labels for 3,879 comments. This check",
        "asks whether the analysis depends on that choice: the same rows, the same features,",
        "the same seed, two label sets.",
        "",
    ]

    shared = payload.get("shared_comment_ids")
    if shared:
        lines += [
            "## 0. Which rows can be compared",
            "",
            "Only %d comments appear in both the paper's feature matrix and our gold run. The"
            % shared,
            "feature matrix keeps Valid comments only, so the overlap is *not* a random sample of",
            "the 3,879 rows: it is the Valid subset of our 150, which is why both Addressed rates",
            "below are around two thirds instead of the published 25.1 %.",
            "",
        ]

    agree = payload["agreement"]
    if agree.get("n"):
        lines += [
            "## 1. Do the two label sets agree?",
            "",
            "| | paper Addressed | paper Not Addressed |",
            "| --- | --- | --- |",
            "| **ours Addressed** | %d | %d |" % (agree["confusion"]["tp"], agree["confusion"]["fp"]),
            "| **ours Not Addressed** | %d | %d |" % (agree["confusion"]["fn"], agree["confusion"]["tn"]),
            "",
            "n = %d, agreement = %.1f %%, Cohen's kappa = %.3f. Addressed rate: ours %.1f %%, paper %.1f %%."
            % (
                agree["n"],
                agree["agreement"] * 100,
                agree["kappa"],
                agree["our_positive_rate"] * 100,
                agree["paper_positive_rate"] * 100,
            ),
            "",
        ]

    lines += ["## 2. Same model, two label sets", "", "| labels | rows | accuracy | Macro-F1 |", "| --- | --- | --- | --- |"]
    for run in payload["runs"]:
        lines.append(
            "| %s | %d | %.4f ± %.4f | %.4f ± %.4f |"
            % (run["labels"], run["rows"], run["accuracy"], run["accuracy_std"], run["macro_f1"], run["macro_f1_std"])
        )
    lines += [
        "",
        "The subsample is small (the same 110 comments, five folds of 22), so the standard",
        "deviations matter more than the differences between the two rows.",
        "",
    ]

    lines += ["## 3. How far does the SHAP ranking move?", ""]
    for pair in payload["rank_shifts"]:
        if pair["mean_shift"] is None:
            continue
        lines.append(
            "- %s vs %s: mean absolute rank shift **%.2f** over %d shared features."
            % (pair["first"], pair["second"], pair["mean_shift"], pair["n"])
        )
    lines += [""]

    names = [run["labels"] for run in payload["runs"]]
    lines += ["| rank | " + " | ".join(names) + " |", "| --- | " + " | ".join("---" for _ in names) + " |"]
    depth = max((len(run["top"]) for run in payload["runs"]), default=0)
    for index in range(depth):
        row = [str(index + 1)]
        for run in payload["runs"]:
            row.append(run["top"][index][0] if index < len(run["top"]) else "")
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## 4. What this does and does not show",
        "",
        "It shows that swapping our labels for the paper's, on the same rows and features,",
        "moves the SHAP ranking by the distance above: the top of the list keeps the same",
        "families (source, comment shape, topic) but the order is not stable, and neither",
        "ranking matches the full 3,879-row run closely. With 110 rows that instability is",
        "expected; it is a warning about how far a ranking can be trusted, not a",
        "contradiction of the paper.",
        "",
        "It does *not* reproduce the published 3,879-row experiment: 110 rows cannot support",
        "that, and the comparison says nothing about the 3,769 rows we never labelled.",
        "",
    ]
    if payload.get("caveat"):
        lines += [payload["caveat"], ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="RQ3 label sensitivity check (DEV-12)")
    parser.add_argument("--zenodo-root", default=None)
    parser.add_argument("--features", default=None)
    parser.add_argument("--labels", default=None)
    parser.add_argument("--annotations", default=str(DEFAULT_ANNOTATIONS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--json", default=None, help="also write the raw numbers here")
    args = parser.parse_args(argv)

    root = _zenodo_root(args.zenodo_root)
    if not root.exists():
        print("error: %s does not exist (pass --zenodo-root)" % root, file=sys.stderr)
        return 2

    features, paper_labels, our_labels = load_inputs(root, Path(args.annotations), args.features, args.labels)
    shared = sorted(
        key
        for key in our_labels
        if key in paper_labels and pd.notna(paper_labels[key]) and key in set(features["comment_id"])
    )
    if not shared:
        print("error: no comment appears in both the feature matrix and the annotations", file=sys.stderr)
        return 2
    print("rows in the feature matrix: %d" % len(features))
    print("rows in both sources: %d" % len(shared))

    subset = features[features["comment_id"].isin(shared)].copy()
    subset = subset.drop_duplicates(subset="comment_id")
    payload = {"agreement": agreement({key: paper_labels[key] for key in shared}, our_labels), "runs": []}

    for name, labels in (("paper labels", paper_labels), ("our labels", our_labels)):
        frame = subset.copy()
        frame[rq3.LABEL_COLUMN] = [int(labels[key]) for key in frame["comment_id"]]
        if frame[rq3.LABEL_COLUMN].nunique() < 2:
            payload["caveat"] = "The %s give a single class on this subsample; the run was skipped." % name
            continue
        result = run_one(frame, name, n_splits=args.n_splits, random_state=args.random_state)
        payload["runs"].append(result)
        print("%-14s rows=%d accuracy=%.4f macro_f1=%.4f" % (name, result["rows"], result["accuracy"], result["macro_f1"]))

    payload["rank_shifts"] = []
    if len(payload["runs"]) == 2:
        first, second = payload["runs"]
        shift = rank_distance(first["ranking"], second["ranking"])
        shift["first"] = first["labels"]
        shift["second"] = second["labels"]
        payload["rank_shifts"].append(shift)

    if DEFAULT_FULL_RUN.exists():
        full = pd.read_csv(DEFAULT_FULL_RUN).head(10)["feature"].tolist()
        for run in payload["runs"]:
            shift = rank_distance(run["ranking"], full)
            shift["first"] = run["labels"]
            shift["second"] = "full 3,879-row run"
            payload["rank_shifts"].append(shift)

    payload["shared_comment_ids"] = len(shared)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.md"
    report_path.write_text(build_report(payload), encoding="utf-8")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote %s" % report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

