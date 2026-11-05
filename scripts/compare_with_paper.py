"""Compare an annotation run with the paper's Table VII (RQ2).

The paper reports four views of the same run: Stage-1 (3 classes), Stage-2
(4 classes), the combined 6-class label, and the binary "Valid-Addressed vs
everything else" view -- each overall and per comment source.

Our CSV has the final six-class label plus the two stage labels, so every view
can be rebuilt from it.  Gold Stage-1/Stage-2 labels are derived from the gold
six-class label (None -> None, General -> General, Valid-* -> Valid).

Usage::

    python scripts/compare_with_paper.py artifacts/deepseek-paper/annotations.csv
    python scripts/compare_with_paper.py run.csv --gold data/gold150.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from swep.metrics import (  # noqa: E402
    ADDRESSED_LABELS,
    accuracy,
    binary_report,
    macro_f1,
)
from swep.schema import KNOWN_SOURCES, SIX_CLASS_LABELS  # noqa: E402

# Paper Table VII (GPT-4.1 Stage-1 + o3-mini Stage-2, temperature 0, 5 runs).
PAPER = {
    ("stage1", "all"): (0.945, 0.908),
    ("stage2", "all"): (0.918, 0.885),
    ("six_class", "all"): (0.861, 0.746),
    ("binary", "all"): (0.915, 0.898),
    ("six_class", "file-level"): (0.836, 0.781),
    ("six_class", "hunk-level"): (0.892, 0.834),
    ("six_class", "human"): (0.856, 0.624),
}


def stage1_of(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    if label.startswith("Valid-"):
        return "Valid"
    return label


def stage2_of(label: Optional[str]) -> Optional[str]:
    return label if label and label.startswith("Valid-") else None


def read_run(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("final_label")]


def read_gold(path: str) -> Dict[str, str]:
    gold: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("gold_label"):
                gold[record["comment_id"]] = record["gold_label"]
    return gold


def summarise(pairs: Iterable[Tuple[str, str]], labels: List[str]) -> Tuple[float, float, int]:
    y_true = [t for t, _ in pairs]
    y_pred = [p for _, p in pairs]
    return accuracy(y_true, y_pred), macro_f1(y_true, y_pred, labels=labels), len(y_true)


def build_views(rows: List[dict], gold: Dict[str, str]) -> Dict[str, List[Tuple[str, str]]]:
    views: Dict[str, List[Tuple[str, str]]] = {
        "stage1": [],
        "stage2": [],
        "six_class": [],
        "binary": [],
    }
    for row in rows:
        cid = row["comment_id"]
        if cid not in gold or str(row.get("error") or ""):
            continue
        gold_label = gold[cid]
        views["six_class"].append((gold_label, row["final_label"]))
        views["binary"].append(
            ("Addressed" if gold_label in ADDRESSED_LABELS else "Not-Addressed",
             "Addressed" if row["final_label"] in ADDRESSED_LABELS else "Not-Addressed")
        )
        gold_stage1 = stage1_of(gold_label)
        pred_stage1 = row.get("stage1_label") or stage1_of(row["final_label"])
        if gold_stage1 and pred_stage1:
            views["stage1"].append((gold_stage1, pred_stage1))
        gold_stage2 = stage2_of(gold_label)
        pred_stage2 = row.get("stage2_label") or ""
        if gold_stage2 and pred_stage2:
            views["stage2"].append((gold_stage2, pred_stage2))
    return views


def fmt(value: Optional[float]) -> str:
    return "-" if value is None else "%.1f%%" % (value * 100.0)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", help="annotations.csv produced by run.py annotate")
    parser.add_argument(
        "--gold",
        default=os.path.join(REPO_ROOT, "data", "gold150.jsonl"),
        help="gold dataset (default: data/gold150.jsonl)",
    )
    args = parser.parse_args(argv)

    rows = read_run(args.annotations)
    gold = read_gold(args.gold)
    views = build_views(rows, gold)
    label_sets = {
        "stage1": ["None", "General", "Valid"],
        "stage2": ["Valid-Uncertain", "Valid-Unaddressed", "Valid-Partially", "Valid-Fully"],
        "six_class": list(SIX_CLASS_LABELS),
        "binary": ["Addressed", "Not-Addressed"],
    }

    print("| view | n | accuracy | macro-F1 | paper accuracy | paper macro-F1 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for view in ("stage1", "stage2", "six_class", "binary"):
        pairs = views[view]
        if not pairs:
            print("| %s | 0 | - | - | - | - |" % view)
            continue
        acc, f1, n = summarise(pairs, label_sets[view])
        paper = PAPER.get((view, "all"))
        print(
            "| %s | %d | %s | %s | %s | %s |"
            % (view, n, fmt(acc), fmt(f1), fmt(paper[0]) if paper else "-",
               fmt(paper[1]) if paper else "-")
        )

    print()
    print("| source | n | accuracy | macro-F1 | paper accuracy | paper macro-F1 |")
    print("| --- | --- | --- | --- | --- | --- |")
    rows_by_id = {row["comment_id"]: row for row in rows if str(row.get("error") or "") == ""}
    for source in KNOWN_SOURCES:
        pairs = [
            (gold[cid], rows_by_id[cid]["final_label"])
            for cid in rows_by_id
            if cid in gold and (rows_by_id[cid].get("source") or "") == source
        ]
        if not pairs:
            print("| %s | 0 | - | - | - | - |" % source)
            continue
        acc, f1, n = summarise(pairs, label_sets["six_class"])
        paper = PAPER.get(("six_class", source))
        print(
            "| %s | %d | %s | %s | %s | %s |"
            % (source, n, fmt(acc), fmt(f1), fmt(paper[0]) if paper else "-",
               fmt(paper[1]) if paper else "-")
        )

    # ``binary_report`` maps six-class labels itself, so hand it the 6-class pairs.
    report = binary_report(
        [t for t, _ in views["six_class"]], [p for _, p in views["six_class"]]
    )
    print()
    print("binary detail: %s" % report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
