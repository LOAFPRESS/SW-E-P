"""Compare two annotation runs on the same gold set (A/B, or repeat stability).

Both CSVs come from ``run.py annotate``.  The script prints, for each run, the
same four views used in the paper (Stage-1 / Stage-2 / six-class / binary),
then the agreement between the two runs and the label transitions that make up
the disagreement.

Usage::

    python scripts/compare_runs.py artifacts/deepseek-paper/annotations.csv \
        artifacts/deepseek-v21/annotations.csv --labels v2 v2.1
    python scripts/compare_runs.py a.csv b.csv --json artifacts/ab.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from swep.metrics import (  # noqa: E402
    ADDRESSED_LABELS,
    accuracy,
    binary_report,
    macro_f1,
)
from swep.schema import SIX_CLASS_LABELS  # noqa: E402

STAGE1_LABELS = ["None", "General", "Valid"]
STAGE2_LABELS = list(SIX_CLASS_LABELS[2:])
BINARY_LABELS = ["Addressed", "Not-Addressed"]


def stage1_of(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    if label.startswith("Valid-"):
        return "Valid"
    return label


def stage2_of(label: Optional[str]) -> Optional[str]:
    return label if label and label.startswith("Valid-") else None


def as_binary(label: str) -> str:
    return "Addressed" if label in ADDRESSED_LABELS else "Not-Addressed"


def read_run(path: str) -> Dict[str, dict]:
    rows: Dict[str, dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("error") or "").strip():
                continue
            if not row.get("final_label"):
                continue
            rows[str(row["comment_id"])] = row
    return rows


def read_gold(path: str) -> Dict[str, str]:
    gold: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("gold_label"):
                gold[str(record["comment_id"])] = record["gold_label"]
    return gold


def view_pairs(rows: Dict[str, dict], gold: Dict[str, str]) -> Dict[str, List[Tuple[str, str]]]:
    views: Dict[str, List[Tuple[str, str]]] = {
        "stage1": [],
        "stage2": [],
        "six_class": [],
        "binary": [],
    }
    for cid, row in rows.items():
        gold_label = gold.get(cid)
        if not gold_label:
            continue
        predicted = row["final_label"]
        views["six_class"].append((gold_label, predicted))
        views["binary"].append((as_binary(gold_label), as_binary(predicted)))
        gold_stage1 = stage1_of(gold_label)
        pred_stage1 = row.get("stage1_label") or stage1_of(predicted)
        if gold_stage1 and pred_stage1:
            views["stage1"].append((gold_stage1, pred_stage1))
        gold_stage2 = stage2_of(gold_label)
        pred_stage2 = row.get("stage2_label") or ""
        if gold_stage2 and pred_stage2:
            views["stage2"].append((gold_stage2, pred_stage2))
    return views


def summarise(
    pairs: List[Tuple[str, str]], labels: List[str]
) -> Dict[str, float]:
    y_true = [t for t, _ in pairs]
    y_pred = [p for _, p in pairs]
    return {
        "n": float(len(y_true)),
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred, labels=labels),
    }


def fmt(value: float) -> str:
    return "%.1f%%" % (value * 100.0)


def metrics_table(views: Dict[str, List[Tuple[str, str]]], label_sets: Dict[str, List[str]]) -> Dict[str, dict]:
    return {
        view: summarise(views[view], label_sets[view])
        for view in ("stage1", "stage2", "six_class", "binary")
        if views[view]
    }


def agreement(rows_a: Dict[str, dict], rows_b: Dict[str, dict]) -> dict:
    shared = sorted(set(rows_a) & set(rows_b))
    changed = [
        (cid, rows_a[cid]["final_label"], rows_b[cid]["final_label"])
        for cid in shared
        if rows_a[cid]["final_label"] != rows_b[cid]["final_label"]
    ]
    transitions: Dict[str, int] = {}
    for _, before, after in changed:
        key = "%s -> %s" % (before, after)
        transitions[key] = transitions.get(key, 0) + 1
    stage1_changed = [
        cid
        for cid in shared
        if (rows_a[cid].get("stage1_label") or "") != (rows_b[cid].get("stage1_label") or "")
    ]
    return {
        "shared": len(shared),
        "changed": len(changed),
        "agreement_rate": (len(shared) - len(changed)) / float(len(shared)) if shared else 0.0,
        "stage1_changed": len(stage1_changed),
        "transitions": dict(sorted(transitions.items(), key=lambda kv: -kv[1])),
        "examples": [
            {
                "comment_id": cid,
                "a": before,
                "b": after,
                "source": rows_a[cid].get("source") or "",
            }
            for cid, before, after in changed[:15]
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a", help="first annotations.csv")
    parser.add_argument("run_b", help="second annotations.csv")
    parser.add_argument(
        "--gold",
        default=os.path.join(REPO_ROOT, "data", "gold150.jsonl"),
        help="gold dataset (default: data/gold150.jsonl)",
    )
    parser.add_argument("--labels", nargs=2, default=["A", "B"], metavar=("A", "B"))
    parser.add_argument("--json", help="write the whole comparison to this JSON file")
    args = parser.parse_args(argv)

    name_a, name_b = args.labels
    rows_a = read_run(args.run_a)
    rows_b = read_run(args.run_b)
    gold = read_gold(args.gold)
    label_sets = {
        "stage1": STAGE1_LABELS,
        "stage2": STAGE2_LABELS,
        "six_class": list(SIX_CLASS_LABELS),
        "binary": BINARY_LABELS,
    }

    metrics = {
        name_a: metrics_table(view_pairs(rows_a, gold), label_sets),
        name_b: metrics_table(view_pairs(rows_b, gold), label_sets),
    }
    compared = agreement(rows_a, rows_b)

    print("| view | n | %s acc | %s F1 | %s acc | %s F1 |" % (name_a, name_a, name_b, name_b))
    print("| --- | --- | --- | --- | --- | --- |")
    for view in ("stage1", "stage2", "six_class", "binary"):
        left = metrics[name_a].get(view)
        right = metrics[name_b].get(view)
        if not left and not right:
            continue
        print(
            "| %s | %s | %s | %s | %s | %s |"
            % (
                view,
                int((left or right)["n"]),
                fmt(left["accuracy"]) if left else "-",
                fmt(left["macro_f1"]) if left else "-",
                fmt(right["accuracy"]) if right else "-",
                fmt(right["macro_f1"]) if right else "-",
            )
        )

    print()
    print(
        "agreement: %d/%d = %s (stage-1 label changed on %d record(s))"
        % (
            compared["shared"] - compared["changed"],
            compared["shared"],
            fmt(compared["agreement_rate"]),
            compared["stage1_changed"],
        )
    )
    if compared["transitions"]:
        print()
        print("| %s -> %s | n |" % (name_a, name_b))
        print("| --- | --- |")
        for key, count in compared["transitions"].items():
            print("| %s | %d |" % (key, count))

    binary = binary_report(
        [t for t, _ in view_pairs(rows_b, gold)["six_class"]],
        [p for _, p in view_pairs(rows_b, gold)["six_class"]],
    )
    print()
    print("%s binary detail: %s" % (name_b, binary))

    if args.json:
        payload = {
            "gold": os.path.abspath(args.gold),
            "runs": {name_a: os.path.abspath(args.run_a), name_b: os.path.abspath(args.run_b)},
            "metrics": metrics,
            "agreement": compared,
        }
        parent = os.path.dirname(os.path.abspath(args.json))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        print()
        print("wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
