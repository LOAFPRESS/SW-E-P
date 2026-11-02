"""Output writers: annotated CSV, run summary, and a markdown run report.

The CSV schema is fixed by :data:`swep.schema.CSV_COLUMNS` and is the contract
with the Random-Forest stage (REQ-1.8): consumers may rely on both the column
names and their order.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .metrics import binary_report, classification_report, label_distribution, to_binary
from .schema import ADDRESSED_LABELS, CSV_COLUMNS, SIX_CLASS_LABELS, AnnotationRecord


def write_annotations_csv(annotations: List[AnnotationRecord], path) -> Path:
    """Write the annotated rows with the fixed schema. Returns the path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for annotation in annotations:
            writer.writerow(annotation.to_row())
    return output_path


def write_json(payload: Dict[str, Any], path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return output_path


def summarize_run(
    result,
    dataset_stats: Dict[str, Any],
    config,
    prompts,
    fingerprint: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the machine-readable summary of one annotation run."""
    annotations = result.annotations
    final_labels = [item.final_label or "(unset)" for item in annotations if not item.error]
    stage1_labels = [item.stage1_label for item in annotations if not item.error]

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_name": config.get("run.name"),
        "run_fingerprint": fingerprint,
        "configuration": config.describe(),
        "prompts": prompts.describe(),
        "dataset": dataset_stats,
        "pipeline": result.stats.as_dict(),
        "labels": {
            "stage1": label_distribution(
                stage1_labels, ["None", "General", "Valid"]
            ),
            "final_six_class": label_distribution(final_labels, SIX_CLASS_LABELS),
            "addressed": sum(1 for item in annotations if item.is_addressed),
            "addressed_rate": round(
                sum(1 for item in annotations if item.is_addressed) / float(len(annotations)), 4
            )
            if annotations
            else 0.0,
        },
        "errors": [
            {"comment_id": item.comment_id, "error": item.error}
            for item in annotations
            if item.error
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def evaluate_against_gold(
    annotations: List[AnnotationRecord],
    gold: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Compare predictions with gold labels for the comments that have one."""
    pairs = [
        (gold[item.comment_id], item.final_label)
        for item in annotations
        if item.comment_id in gold and not item.error and item.final_label
    ]
    if not pairs:
        return None
    y_true = [truth for truth, _ in pairs]
    y_pred = [pred for _, pred in pairs]
    return {
        "n": len(pairs),
        "six_class": classification_report(y_true, y_pred, SIX_CLASS_LABELS),
        "binary": binary_report(y_true, y_pred),
        "addressed_rate_gold": round(
            sum(1 for label in y_true if label in ADDRESSED_LABELS) / float(len(y_true)), 4
        ),
        "addressed_rate_pred": round(
            sum(1 for label in y_pred if label in ADDRESSED_LABELS) / float(len(y_pred)), 4
        ),
    }


def write_run_report(summary: Dict[str, Any], path) -> Path:
    """Human-readable markdown summary, handy for the weekly meeting notes."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_stats = summary.get("pipeline", {})
    labels = summary.get("labels", {})
    dataset = summary.get("dataset", {})

    lines = [
        "# Annotation run: %s" % summary.get("run_name", "(unnamed)"),
        "",
        "- Generated: %s" % summary.get("generated_at", ""),
        "- Configuration: %s" % summary.get("configuration", ""),
        "- Prompts: %s" % summary.get("prompts", ""),
        "- Fingerprint: `%s`" % summary.get("run_fingerprint", ""),
        "",
        "## Dataset",
        "",
        "- Records: %s (by source: %s)" % (
            dataset.get("count"),
            ", ".join("%s=%s" % item for item in (dataset.get("by_source") or {}).items()) or "n/a",
        ),
        "- With review diff: %s; with subsequent changes: %s; with gold label: %s" % (
            dataset.get("with_review_diff"),
            dataset.get("with_subsequent_changes"),
            dataset.get("with_gold_label"),
        ),
        "",
        "## Pipeline",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for key in (
        "processed",
        "completed",
        "failed",
        "llm_calls",
        "stage2_calls",
        "cache_hits",
        "retries",
        "parse_retries",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "duration_s",
        "stopped_reason",
    ):
        lines.append("| %s | %s |" % (key, pipeline_stats.get(key)))

    lines += ["", "## Label distribution", ""]
    for scheme in ("stage1", "final_six_class"):
        counts = labels.get(scheme) or {}
        total = sum(counts.values()) or 1
        lines.append("**%s**" % scheme)
        lines.append("")
        for label, count in counts.items():
            lines.append("- %s: %s (%.1f%%)" % (label, count, 100.0 * count / total))
        lines.append("")

    evaluation = summary.get("evaluation")
    if evaluation:
        lines += ["## Against gold labels", ""]
        lines.append("- n = %s" % evaluation.get("n"))
        lines.append("- accuracy (6 classes) = %s" % evaluation["six_class"]["accuracy"])
        lines.append("- macro-F1 (6 classes) = %s" % evaluation["six_class"]["macro_f1"])
        lines.append("- binary accuracy = %s" % evaluation["binary"]["accuracy"])
        lines.append("- gold addressed rate = %s; predicted = %s" % (
            evaluation.get("addressed_rate_gold"),
            evaluation.get("addressed_rate_pred"),
        ))
        lines.append("")
        lines.append("| label | support | precision | recall | f1 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for label, values in evaluation["six_class"]["per_class"].items():
            lines.append(
                "| %s | %s | %s | %s | %s |"
                % (label, values["support"], values["precision"], values["recall"], values["f1"])
            )
        lines.append("")

    errors = summary.get("errors") or []
    lines += ["## Errors", ""]
    if errors:
        for item in errors[:20]:
            lines.append("- `%s`: %s" % (item.get("comment_id"), item.get("error")))
    else:
        lines.append("- none")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


__all__ = [
    "write_annotations_csv",
    "write_json",
    "summarize_run",
    "evaluate_against_gold",
    "write_run_report",
    "to_binary",
]
