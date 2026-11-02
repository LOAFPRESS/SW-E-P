"""Canonical data model shared by the annotation pipeline and its consumers.

Two structures matter:

``ReviewRecord``
    One row of the input dataset, i.e. an AI- or human-authored review comment
    together with the code context the paper's annotators were given
    ("reviewed changes" for Stage-1 and "subsequent file modifications" for
    Stage-2).  Field names are the internal schema; the loader maps the raw
    Zenodo column names onto them (see :mod:`swep.data.loader`).

``AnnotationRecord``
    One row of the annotated output: Stage-1 label + extracted issue checklist,
    the optional Stage-2 adoption label, the rationale, and the bookkeeping
    needed for cost/token reporting and reproducible re-runs.

Label sets (paper Section IV-B):

Stage-1 (validity)
    ``None``     - no issue/suggestion at all
    ``General``  - only overly general issues/suggestions
    ``Valid``    - at least one specific, actionable issue/suggestion

Stage-2 (adoption, only for ``Valid`` comments)
    ``Valid-Uncertain``    - insufficient information (file deleted, heavy refactor)
    ``Valid-Unaddressed``  - none of the identified items addressed
    ``Valid-Partially``    - some but not all items addressed
    ``Valid-Fully``        - all items addressed
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .errors import DataValidationError

#: The six classes used for the headline evaluation (paper Table VII).
SIX_CLASS_LABELS = [
    "None",
    "General",
    "Valid-Uncertain",
    "Valid-Unaddressed",
    "Valid-Partially",
    "Valid-Fully",
]

#: Binary scheme accepted by the customer: Addressed vs. everything else.
ADDRESSED_LABELS = ("Valid-Partially", "Valid-Fully")

#: Sources used in the gold-standard sample (50 comments each in the paper).
KNOWN_SOURCES = ("file-level", "hunk-level", "human")


class Stage1Label(str, Enum):
    """Validity of a review comment (paper Stage-1)."""

    NONE = "None"
    GENERAL = "General"
    VALID = "Valid"

    @classmethod
    def coerce(cls, value):
        """Normalise a model-produced value into a ``Stage1Label``.

        Accepts case differences, surrounding punctuation and the aliases
        "Invalid" (-> None) / "Actionable" (-> Valid) that models sometimes
        invent.  Raises ``ValueError`` when the value is not recognisable.
        """
        if isinstance(value, cls):
            return value
        raw = str(value or "").strip().strip(".:;\"'`*").lower()
        aliases = {
            "none": cls.NONE,
            "invalid": cls.NONE,
            "not-valid": cls.NONE,
            "no": cls.NONE,
            "general": cls.GENERAL,
            "generic": cls.GENERAL,
            "vague": cls.GENERAL,
            "valid": cls.VALID,
            "actionable": cls.VALID,
            "yes": cls.VALID,
        }
        if raw in aliases:
            return aliases[raw]
        # Models occasionally answer Stage-1 with a Stage-2 label ("Valid-Fully");
        # the validity dimension is still "Valid", so keep the prefix.
        if raw.startswith("valid"):
            return cls.VALID
        raise ValueError(
            "unrecognised Stage-1 label: %r (expected one of None, General, Valid)" % (value,)
        )


class Stage2Label(str, Enum):
    """Adoption status of a Valid comment (paper Stage-2)."""

    UNCERTAIN = "Valid-Uncertain"
    UNADDRESSED = "Valid-Unaddressed"
    PARTIALLY = "Valid-Partially"
    FULLY = "Valid-Fully"

    @classmethod
    def coerce(cls, value):
        """Normalise a model-produced value into a ``Stage2Label``."""
        if isinstance(value, cls):
            return value
        raw = str(value or "").strip().strip(".:;\"'`*")
        key = raw.lower().replace("_", "-").replace(" ", "-")
        aliases = {
            "valid-uncertain": cls.UNCERTAIN,
            "uncertain": cls.UNCERTAIN,
            "valid-unaddressed": cls.UNADDRESSED,
            "unaddressed": cls.UNADDRESSED,
            "not-addressed": cls.UNADDRESSED,
            "valid-partially": cls.PARTIALLY,
            "valid-partial": cls.PARTIALLY,
            "partially": cls.PARTIALLY,
            "partially-addressed": cls.PARTIALLY,
            "valid-fully": cls.FULLY,
            "fully": cls.FULLY,
            "fully-addressed": cls.FULLY,
            "addressed": cls.FULLY,
        }
        if key not in aliases:
            raise ValueError("unrecognised Stage-2 label: %r" % (value,))
        return aliases[key]


@dataclass
class ReviewRecord:
    """One review comment plus the context needed for both stages."""

    comment_id: str
    source: str
    comment_text: str
    review_diff: str = ""
    subsequent_changes: str = ""
    action_id: Optional[str] = None
    action_name: Optional[str] = None
    trigger: Optional[str] = None
    granularity: Optional[str] = None
    repo: Optional[str] = None
    pr_number: Optional[str] = None
    gold_label: Optional[str] = None
    gold_issues: Optional[List[str]] = None
    synthetic: bool = False

    def validate(self):
        """Raise ``DataValidationError`` when a mandatory field is missing/empty."""
        problems = []
        if not str(self.comment_id or "").strip():
            problems.append("comment_id is empty")
        if not str(self.source or "").strip():
            problems.append("source is empty")
        if not str(self.comment_text or "").strip():
            problems.append("comment_text is empty (comment_id=%s)" % (self.comment_id,))
        if problems:
            raise DataValidationError("; ".join(problems))
        return self


@dataclass
class AnnotationRecord:
    """One annotated row, i.e. the unit exported to ``annotations.csv``."""

    comment_id: str
    source: str
    stage1_label: str = ""
    stage1_issues: List[str] = field(default_factory=list)
    stage2_label: Optional[str] = None
    final_label: str = ""
    stage1_rationale: str = ""
    stage2_rationale: str = ""
    addressed_items: List[str] = field(default_factory=list)
    unaddressed_items: List[str] = field(default_factory=list)
    model_stage1: str = ""
    model_stage2: str = ""
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached_calls: int = 0
    attempts: int = 0
    latency_ms: float = 0.0
    error: str = ""

    @property
    def is_addressed(self) -> bool:
        """Binary view used by the customer: Partially/Fully -> addressed.

        Failed rows are always "not addressed": no label was produced, so the
        row must not count as a positive example downstream.
        """
        if self.error:
            return False
        return self.final_label in ADDRESSED_LABELS

    @property
    def failed(self) -> bool:
        return bool(self.error)

    def to_row(self) -> Dict[str, Any]:
        """Flat, JSON-friendly representation used for the output CSV."""
        return {
            "comment_id": self.comment_id,
            "source": self.source,
            "stage1_label": self.stage1_label,
            "stage1_issues": _join(self.stage1_issues),
            "stage2_label": self.stage2_label or "",
            "final_label": self.final_label,
            "is_addressed": int(self.is_addressed),
            "stage1_rationale": self.stage1_rationale,
            "stage2_rationale": self.stage2_rationale,
            "addressed_items": _join(self.addressed_items),
            "unaddressed_items": _join(self.unaddressed_items),
            "model_stage1": self.model_stage1,
            "model_stage2": self.model_stage2,
            "prompt_version": self.prompt_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "cached_calls": self.cached_calls,
            "attempts": self.attempts,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


#: Column order of ``annotations.csv`` -- treated as a stable, published schema.
CSV_COLUMNS = [
    "comment_id",
    "source",
    "stage1_label",
    "stage1_issues",
    "stage2_label",
    "final_label",
    "is_addressed",
    "stage1_rationale",
    "stage2_rationale",
    "addressed_items",
    "unaddressed_items",
    "model_stage1",
    "model_stage2",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "cached_calls",
    "attempts",
    "latency_ms",
    "error",
]


def _join(items: Optional[List[str]]) -> str:
    """Serialise a list of free-text items into one CSV cell."""
    if not items:
        return ""
    cleaned = [str(item).strip().replace("\n", " ") for item in items if str(item).strip()]
    return " | ".join(cleaned)


def final_label_for(stage1_label: str, stage2_label: Optional[str]) -> str:
    """Combine the two stages into one of the six evaluation classes.

    Non-``Valid`` comments carry their Stage-1 label through unchanged.  A
    ``Valid`` comment without a Stage-2 answer is reported as
    ``Valid-Uncertain`` (the paper's "cannot tell" bucket) rather than as an
    empty label, so downstream aggregates never silently drop a row.
    """
    if stage1_label != Stage1Label.VALID.value:
        return stage1_label
    if not stage2_label:
        return Stage2Label.UNCERTAIN.value
    try:
        return Stage2Label.coerce(stage2_label).value
    except ValueError:
        raise ValueError(
            "unexpected Stage-2 label %r for a Valid comment (expected one of %s)"
            % (stage2_label, ", ".join(label.value for label in Stage2Label))
        )
