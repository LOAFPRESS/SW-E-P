"""Dataset loading and schema adaptation (REQ-1.1).

The public Zenodo release, the internal fixtures and the final integration with
Member A all use *different* column names for the same concepts.  Rather than
hard-coding one layout, the loader takes an explicit ``data.column_map`` in the
YAML configuration::

    data:
      column_map:
        comment_id: "review_comment_id"
        comment_text: "comment_body"
        review_diff: "code_diff"

Every target field also has a list of obvious aliases, so a well-named CSV works
without any mapping.  When a mandatory field cannot be found, the loader stops
with a message that lists the missing fields **and** the columns that do exist,
because guessing would silently corrupt the annotation results.
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..errors import DataValidationError
from ..logging_utils import get_logger
from ..schema import KNOWN_SOURCES, ReviewRecord

#: Fields without which a record cannot be annotated.
REQUIRED_FIELDS = ("comment_id", "source", "comment_text")

#: Every field the pipeline understands, with fallback aliases.
FIELD_ALIASES: Dict[str, List[str]] = {
    "comment_id": ["comment_id", "commentid", "id", "comment id", "review_comment_id", "review id"],
    "source": ["source", "comment_source", "origin", "level"],
    "comment_text": ["comment_text", "comment", "comment_body", "body", "review_comment", "text"],
    "review_diff": ["review_diff", "diff", "code_diff", "reviewed_changes", "changes_at_review"],
    "subsequent_changes": [
        "subsequent_changes",
        "subsequent_modifications",
        "later_changes",
        "subsequent_diff",
        "addressed_diff",
    ],
    "reviewed_path": ["reviewed_path", "diff_path", "path", "reviewed_file", "file_path"],
    "new_path": ["new_path", "file_name", "new_file_path", "renamed_path"],
    "action_id": ["action_id", "actionid", "workflow_id", "action"],
    "action_name": ["action_name", "action_type", "workflow_name"],
    "trigger": ["trigger", "trigger_type", "event"],
    "granularity": ["granularity", "review_granularity"],
    "repo": ["repo", "repository", "repo_name", "full_name"],
    "pr_number": ["pr_number", "pr", "pull_number", "pull_request"],
    "gold_label": ["gold_label", "human_label", "label", "annotation", "true_label"],
    "gold_issues": ["gold_issues", "issues", "issue_list"],
    "synthetic": ["synthetic", "is_synthetic"],
}

#: Fields copied verbatim (everything else is coerced to text).
_SCALAR_FIELDS = (
    "comment_id",
    "source",
    "action_id",
    "action_name",
    "trigger",
    "granularity",
    "repo",
    "pr_number",
    "reviewed_path",
    "new_path",
    "gold_label",
)
_TEXT_FIELDS = ("comment_text", "review_diff", "subsequent_changes")


def _lookup(row: Dict[str, Any], candidates: Iterable[str]) -> Optional[Any]:
    """Case-insensitive, whitespace-tolerant lookup of the first present column."""
    normalised = {str(key).strip().lower(): value for key, value in row.items()}
    for candidate in candidates:
        key = str(candidate).strip().lower()
        if key in normalised:
            value = normalised[key]
            if isinstance(value, str):
                value = value.strip()
            return value
    return None


def _collect_rows(path: Path, fmt: str) -> List[Dict[str, Any]]:
    """Read the dataset into a list of raw dictionaries."""
    suffix = path.suffix.lower()
    if fmt == "auto":
        fmt = {".jsonl": "jsonl", ".json": "json", ".csv": "csv"}.get(suffix)
        if fmt is None:
            raise DataValidationError(
                "cannot infer data.format from extension %r; set data.format explicitly" % suffix
            )

    if fmt == "jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DataValidationError(
                        "%s line %d is not valid JSON: %s" % (path.name, line_no, exc)
                    )
                if not isinstance(payload, dict):
                    raise DataValidationError(
                        "%s line %d is not a JSON object" % (path.name, line_no)
                    )
                rows.append(payload)
        return rows

    if fmt == "json":
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            for key in ("records", "data", "items", "comments"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise DataValidationError(
                "%s must contain a JSON array of objects, or an object with a "
                "'records'/'data'/'items' array" % path.name
            )
        return [row for row in payload if isinstance(row, dict)]

    if fmt == "csv":
        import pandas as pd

        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        return frame.to_dict(orient="records")

    raise DataValidationError("unsupported data.format: %r" % fmt)


def _apply_column_map(raw_row: Dict[str, Any], column_map: Dict[str, Any]) -> Dict[str, Any]:
    """Translate one raw row into the internal schema."""
    mapped: Dict[str, Any] = {}
    for field, fallback in FIELD_ALIASES.items():
        override = column_map.get(field)
        if override:
            candidates = override if isinstance(override, (list, tuple)) else [override]
            value = _lookup(raw_row, candidates)
            if value is None:
                # Still try the aliases: a partial mapping should not lose data.
                value = _lookup(raw_row, fallback)
        else:
            value = _lookup(raw_row, fallback)
        if value is not None:
            mapped[field] = value
    return mapped


def _to_record(mapped: Dict[str, Any], index: int) -> ReviewRecord:
    """Convert a mapped row to a validated :class:`ReviewRecord`."""
    missing = [field for field in REQUIRED_FIELDS if not str(mapped.get(field, "")).strip()]
    if missing:
        raise DataValidationError(
            "record #%d is missing mandatory field(s): %s" % (index, ", ".join(missing))
        )

    values: Dict[str, Any] = {}
    for field in _SCALAR_FIELDS:
        value = mapped.get(field)
        values[field] = str(value).strip() if value not in (None, "") else None
    for field in _TEXT_FIELDS:
        value = mapped.get(field)
        values[field] = str(value) if value not in (None, "") else ""

    gold_issues = mapped.get("gold_issues") or []
    if isinstance(gold_issues, str):
        gold_issues = [part.strip() for part in gold_issues.replace("\n", "|").split("|") if part.strip()]
    elif isinstance(gold_issues, (list, tuple)):
        gold_issues = [str(item).strip() for item in gold_issues if str(item).strip()]
    else:
        gold_issues = []

    synthetic_raw = mapped.get("synthetic", False)
    if isinstance(synthetic_raw, str):
        synthetic = synthetic_raw.strip().lower() in ("1", "true", "yes", "y")
    else:
        synthetic = bool(synthetic_raw)

    record = ReviewRecord(
        comment_id=values["comment_id"],
        source=values["source"],
        comment_text=values["comment_text"],
        review_diff=values["review_diff"],
        subsequent_changes=values["subsequent_changes"],
        reviewed_path=values.get("reviewed_path"),
        new_path=values.get("new_path"),
        action_id=values.get("action_id"),
        action_name=values.get("action_name"),
        trigger=values.get("trigger"),
        granularity=values.get("granularity"),
        repo=values.get("repo"),
        pr_number=values.get("pr_number"),
        gold_label=values.get("gold_label"),
        gold_issues=gold_issues,
        synthetic=synthetic,
    )
    record.validate()
    return record


def load_dataset(
    path,
    fmt: str = "auto",
    column_map: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    split: Optional[Any] = None,
    logger=None,
) -> List[ReviewRecord]:
    """Load, map, validate and (optionally) truncate the dataset.

    Parameters
    ----------
    path:
        Dataset file (JSONL, JSON array, or CSV).
    fmt:
        ``auto`` (default), ``jsonl``, ``json`` or ``csv``.
    column_map:
        ``target_field -> source column`` overrides from ``data.column_map``.
    limit:
        Keep at most this many records *after* filtering (REQ-1.16).
    split:
        Optional filter. A string keeps records whose ``source`` equals it; a
        mapping ``{"field": "...", "values": [...]}`` keeps records whose field
        value is in the list.
    """
    log = logger or get_logger()
    data_path = Path(path)
    if not data_path.is_file():
        raise DataValidationError("dataset not found: %s" % data_path)

    rows = _collect_rows(data_path, fmt)
    log.info("read %d raw row(s) from %s", len(rows), data_path.name)

    available = sorted({str(key).strip() for row in rows[:1] for key in row.keys()}) if rows else []
    records: List[ReviewRecord] = []
    for index, raw_row in enumerate(rows, start=1):
        mapped = _apply_column_map(raw_row, column_map or {})
        try:
            records.append(_to_record(mapped, index))
        except DataValidationError as exc:
            raise DataValidationError(
                "%s\nAvailable columns in the dataset: %s\n"
                "Map the fields under data.column_map in the configuration."
                % (exc, ", ".join(available) or "(none)")
            )

    if split:
        records = _apply_split(records, split, log)

    unknown_sources = {record.source for record in records if record.source not in KNOWN_SOURCES}
    if unknown_sources:
        log.warning(
            "non-standard source value(s) %s; expected one of %s",
            sorted(unknown_sources),
            list(KNOWN_SOURCES),
        )

    if limit is not None:
        if int(limit) < len(records):
            log.info("limit=%s keeps the first %s of %d record(s)", limit, limit, len(records))
        records = records[: int(limit)]

    if not records:
        raise DataValidationError(
            "the dataset produced no usable record (path=%s, split=%r); check the "
            "file and the data.split filter" % (data_path, split)
        )

    duplicates = len(records) - len({record.comment_id for record in records})
    if duplicates:
        log.warning("%d duplicate comment_id value(s) found", duplicates)
    return records


def _apply_split(records: List[ReviewRecord], split: Any, log) -> List[ReviewRecord]:
    """Keep only the records selected by the ``data.split`` filter."""
    if isinstance(split, str):
        field, values = "source", [split]
    elif isinstance(split, dict):
        field = str(split.get("field", "source"))
        values = split.get("values")
        values = [values] if isinstance(values, str) else list(values or [])
    else:
        raise DataValidationError("data.split must be a string or a mapping")
    if not hasattr(records[0], field):
        raise DataValidationError("data.split refers to unknown field %r" % field)
    wanted = {str(value).strip().lower() for value in values}
    kept = [record for record in records if str(getattr(record, field, "")).strip().lower() in wanted]
    log.info("split %s in %s keeps %d record(s)", field, sorted(wanted), len(kept))
    return kept


def describe_dataset(records: List[ReviewRecord]) -> Dict[str, Any]:
    """Counts used in the run summary and in the report."""
    by_source: Dict[str, int] = {}
    for record in records:
        by_source[record.source] = by_source.get(record.source, 0) + 1
    return {
        "count": len(records),
        "by_source": dict(sorted(by_source.items())),
        "with_review_diff": sum(1 for record in records if record.review_diff.strip()),
        "with_reviewed_path": sum(1 for record in records if (record.reviewed_path or "").strip()),
        "with_subsequent_changes": sum(1 for record in records if record.subsequent_changes.strip()),
        "with_gold_label": sum(1 for record in records if record.gold_label),
        "synthetic": sum(1 for record in records if record.synthetic),
    }
