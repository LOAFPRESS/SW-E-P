"""Build the paper's 150-comment gold dataset from the Zenodo appendix.

The Zenodo package (``10.5281/zenodo.19562449``) ships the sampled reviews and
the human labels as two *separate* files per review granularity::

    llm_analysis/input/sampled_file_level_review.csv    # 50 comments + context
    llm_analysis/labeled/(resolved)sampled_file_level_review.csv   # 50 labels

and the same pair for ``human`` and ``patch_level`` (``hunk-level`` in our
schema).  The two files are joined on ``Comment_URL``; every input row must find
exactly one label, otherwise the build stops instead of silently producing a
smaller gold set (REQ-1.1).

Labels are stored as compact codes, e.g. ``2,2`` for "contains a valid issue
(stage-1 code 2) and it is fully addressed (stage-2 code 2)".  :data:`GOLD_LABELS`
maps them onto the six classes used by the pipeline and by the paper's
Table VII.  The exact mapping is taken from the appendix implementation:

* ``extract_suggestion.py`` emits the stage-1 code (0 = no items, 1 = general
  only, 2 = valid items);
* ``analyze_addressed_status.py::resolve_format`` combines it with the stage-2
  code (-1 = not enough information, 0 = not addressed, 1 = partly addressed,
  2 = fully addressed) as ``"<stage1>,<stage2>"``.

Anything else raises :class:`DataValidationError` listing the offending values,
because an unknown code means we no longer understand the gold data.
"""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..errors import DataValidationError
from ..schema import ReviewRecord

#: Relative locations inside the downloaded Zenodo directory.
INPUT_DIR = Path("llm_analysis") / "input"
LABELED_DIR = Path("llm_analysis") / "labeled"

#: ``(source, input file stem, label file stem)`` -- the label files carry a
#: ``(resolved)`` prefix in the appendix, hence the separate names.
SAMPLES: Tuple[Tuple[str, str, str], ...] = (
    ("file-level", "sampled_file_level_review", "(resolved)sampled_file_level_review"),
    ("hunk-level", "sampled_patch_level_review", "(resolved)sampled_patch_level_review"),
    ("human", "sampled_human_review", "(resolved)sampled_human_review"),
)

#: Gold codes used by the appendix -> six-class label used by the pipeline.
GOLD_LABELS: Dict[str, str] = {
    "0": "None",
    "1": "General",
    "2,-1": "Valid-Uncertain",
    "2,0": "Valid-Unaddressed",
    "2,1": "Valid-Partially",
    "2,2": "Valid-Fully",
}

#: Columns that must exist in the input sample before the join is attempted.
INPUT_COLUMNS = (
    "source_action",
    "Comment_URL",
    "Comment_HTML_URL",
    "Diff_path",
    "New_path",
    "Body",
    "Diff_hunk",
    "Change_Until_Merged",
)

#: Columns that must exist in the labeled sample.
LABEL_COLUMNS = ("Comment_URL", "Final Result")

#: Values that mean "this cell carries no information" in the Zenodo CSVs.
_EMPTY_MARKERS = ("", "nan", "none", "null", "n/a", "na", "<na>", "nat")

#: ``Change_Until_Merged`` sentinel for a file that was deleted after the review.
DELETED_SENTINEL = "File_Deleted"


# --------------------------------------------------------------------- parsing
def normalise_cell(value: Any) -> str:
    """Return a stripped cell, collapsing the CSV's stand-ins for "empty"."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY_MARKERS:
        return ""
    return text


def parse_comment_url(url: str) -> Tuple[Optional[str], Optional[str], str]:
    """Split a GitHub review-comment URL into ``(repo, pr_number, comment_id)``.

    Both URL shapes used by the appendix are understood::

        https://api.github.com/repos/owner/repo/pulls/comments/12345
        https://github.com/owner/repo/pull/42#discussion_r12345

    Missing pieces come back as ``None`` instead of raising: the URL is context,
    not a mandatory field, and a malformed one must not discard a labeled record.
    """
    text = normalise_cell(url)
    repo: Optional[str] = None
    pr_number: Optional[str] = None
    comment_id = ""

    marker = "/repos/"
    if marker in text:
        tail = text.split(marker, 1)[1]
        parts = [part for part in tail.split("/") if part]
        if len(parts) >= 2:
            repo = "%s/%s" % (parts[0], parts[1])
        if "pulls" in parts:
            index = parts.index("pulls")
            if len(parts) > index + 2 and parts[index + 1] == "comments":
                comment_id = parts[index + 2]
        if not comment_id and "comments" in parts:
            index = parts.index("comments")
            if len(parts) > index + 1:
                comment_id = parts[index + 1]

    if "#discussion_r" in text:
        comment_id = comment_id or text.rsplit("#discussion_r", 1)[1].strip()

    if repo is None:
        for host in ("github.com/", "api.github.com/repos/"):
            if host in text:
                tail = text.split(host, 1)[1].split("#", 1)[0]
                parts = [part for part in tail.split("/") if part]
                if len(parts) >= 2:
                    repo = "%s/%s" % (parts[0], parts[1])
                break

    if "/pull/" in text:
        tail = text.split("/pull/", 1)[1]
        digits = ""
        for char in tail:
            if char.isdigit():
                digits += char
            else:
                break
        pr_number = pr_number or (digits or None)

    return repo, pr_number, comment_id


def _read_csv(path: Path, columns: Iterable[str]) -> List[Dict[str, str]]:
    """Read one Zenodo CSV and verify the columns we rely on exist."""
    if not path.is_file():
        raise DataValidationError(
            "Zenodo file not found: %s (download the appendix and point "
            "data.zenodo_root at the extracted folder)" % path
        )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [str(name).strip() for name in (reader.fieldnames or [])]
        missing = [column for column in columns if column not in header]
        if missing:
            raise DataValidationError(
                "%s is missing expected column(s): %s\nAvailable columns: %s"
                % (path.name, ", ".join(missing), ", ".join(header) or "(none)")
            )
        rows = []
        for raw in reader:
            rows.append({str(key).strip(): normalise_cell(value) for key, value in raw.items() if key})
    return rows


def _join(
    inputs: List[Dict[str, str]], labels: List[Dict[str, str]], source: str
) -> Tuple[List[Tuple[Dict[str, str], Dict[str, str]]], List[str]]:
    """Inner-join inputs and labels on ``Comment_URL``."""
    by_url: Dict[str, Dict[str, str]] = {}
    for row in labels:
        url = row.get("Comment_URL", "")
        if not url:
            continue
        by_url.setdefault(url, row)

    joined: List[Tuple[Dict[str, str], Dict[str, str]]] = []
    unlabeled: List[str] = []
    for row in inputs:
        url = row.get("Comment_URL", "")
        label = by_url.get(url)
        if label is None:
            unlabeled.append(url or "(empty Comment_URL)")
            continue
        joined.append((row, label))
    return joined, unlabeled


# ---------------------------------------------------------------------- build
def build_gold_records(root, sources: Optional[Iterable[str]] = None) -> Tuple[List[ReviewRecord], Dict[str, Any]]:
    """Build the gold records from an extracted Zenodo directory.

    Returns ``(records, stats)`` where ``stats`` records the provenance of the
    build (input files, per-source counts, label distribution and the SHA-256 of
    every file that contributed), so a run can state exactly which data it used
    (DOM-1.4).
    """
    base = Path(root)
    if not base.is_dir():
        raise DataValidationError("Zenodo directory not found: %s" % base)

    wanted = {str(source).strip() for source in sources} if sources else None
    records: List[ReviewRecord] = []
    stats: Dict[str, Any] = {
        "zenodo_root": str(base),
        "files": {},
        "per_source": {},
        "unlabeled": {},
        "label_codes": {},
        "deleted_file_rows": 0,
    }

    for source, input_stem, label_stem in SAMPLES:
        if wanted is not None and source not in wanted:
            continue
        input_path = base / INPUT_DIR / ("%s.csv" % input_stem)
        label_path = base / LABELED_DIR / ("%s.csv" % label_stem)

        inputs = _read_csv(input_path, INPUT_COLUMNS)
        labels = _read_csv(label_path, LABEL_COLUMNS)
        joined, unlabeled = _join(inputs, labels, source)

        stats["files"][input_path.name] = _sha256(input_path)
        stats["files"][label_path.name] = _sha256(label_path)
        stats["per_source"][source] = len(joined)
        if unlabeled:
            stats["unlabeled"][source] = unlabeled[:20]

        for row, label in joined:
            code = normalise_cell(label.get("Final Result", ""))
            gold = GOLD_LABELS.get(code)
            if gold is None:
                raise DataValidationError(
                    "unknown gold label code %r in %s (comment %s); expected one "
                    "of %s"
                    % (code, label_path.name, row.get("Comment_URL"), sorted(GOLD_LABELS))
                )
            stats["label_codes"][code] = stats["label_codes"].get(code, 0) + 1

            repo, pr_number, comment_id = parse_comment_url(row.get("Comment_URL", ""))
            # The API URL has repo + comment id, the HTML URL adds the pull
            # request number, so merge both instead of preferring one.
            repo2, pr2, comment_id2 = parse_comment_url(row.get("Comment_HTML_URL", ""))
            repo = repo or repo2
            pr_number = pr_number or pr2
            comment_id = comment_id or comment_id2
            if not comment_id:
                raise DataValidationError(
                    "cannot derive a comment id from %r (source=%s)"
                    % (row.get("Comment_URL"), source)
                )

            subsequent = normalise_cell(row.get("Change_Until_Merged", ""))
            if subsequent == DELETED_SENTINEL:
                stats["deleted_file_rows"] += 1

            record = ReviewRecord(
                comment_id=comment_id,
                source=source,
                granularity=source,
                comment_text=normalise_cell(row.get("Body", "")),
                review_diff=normalise_cell(row.get("Diff_hunk", "")),
                subsequent_changes=subsequent,
                reviewed_path=normalise_cell(row.get("Diff_path", "")) or None,
                new_path=normalise_cell(row.get("New_path", "")) or None,
                action_name=normalise_cell(row.get("source_action", "")) or None,
                repo=repo,
                pr_number=pr_number,
                gold_label=gold,
                synthetic=False,
            )
            records.append(record.validate())

    if not records:
        raise DataValidationError(
            "the gold build produced no record (root=%s, sources=%s)"
            % (base, sorted(wanted) if wanted else "all")
        )

    duplicates = len(records) - len({record.comment_id for record in records})
    stats["count"] = len(records)
    stats["duplicate_comment_ids"] = duplicates
    stats["labels"] = _label_distribution(record.gold_label for record in records)
    return records, stats


def _label_distribution(labels: Iterable[Optional[str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for label in labels:
        key = label or "(missing)"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------- output
def write_jsonl(records: List[ReviewRecord], path) -> Path:
    """Write the built records as JSONL, the format the loader reads natively."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            payload = {
                "comment_id": record.comment_id,
                "source": record.source,
                "granularity": record.granularity,
                "comment_text": record.comment_text,
                "review_diff": record.review_diff,
                "subsequent_changes": record.subsequent_changes,
                "reviewed_path": record.reviewed_path,
                "new_path": record.new_path,
                "action_name": record.action_name,
                "repo": record.repo,
                "pr_number": record.pr_number,
                "gold_label": record.gold_label,
                "synthetic": False,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def write_provenance(stats: Dict[str, Any], path) -> Path:
    """Write the build statistics next to the dataset."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
