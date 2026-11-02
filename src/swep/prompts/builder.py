"""Prompt template loading, rendering and versioning.

Two families of templates ship with the repository:

``v1-reconstructed-*``
    Written before the Zenodo supplementary material was available.  The
    templates describe the annotation rules of the paper in our own words and
    ask for a JSON answer (``{"label": ..., "issues": [...]}``).

``v2-paper-*``
    Reproduces the appendix prompts (``prompts/stage1_v2_original.md``,
    ``prompts/stage2_v2_original.md``) verbatim, including the plain-text answer
    format (``Issues or Suggestions:`` / ``Classification:``).  Those files were
    extracted from ``extract_suggestion_prompter_3.py`` and
    ``analyze_addressed_prompter_4.py`` of the Zenodo package.

The answer format therefore follows the *template*, not a global constant: a
run configured with ``prompts.format: text`` parses the appendix format, and a
run configured with ``prompts.format: json`` parses JSON.  Every change to a
template must bump ``prompts.version`` in the YAML configuration and be recorded
in ``prompts/CHANGELOG.md`` (DOM-1.2).

Templates use :class:`string.Template` placeholders such as ``$comment_text``;
the renderer receives a superset of every placeholder both families use, so a
template only sees the values it references.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Dict, List, Optional

from ..errors import ConfigError
from ..schema import ReviewRecord

#: Answer formats understood by the parser (``swep.llm.parsing``).
OUTPUT_FORMATS = ("json", "text")

#: System message for the JSON templates.  Keeping it short leaves room for the
#: (much longer) review context in the user message.
SYSTEM_PROMPT = (
    "You are a meticulous software engineering researcher. "
    "Answer with a single JSON object and no additional text."
)

#: System message for the appendix-style templates: they specify their own output
#: format, so this only sets the role and must not contradict the template.
SYSTEM_PROMPT_TEXT = (
    "You are a meticulous software engineering researcher who follows the "
    "instructions in the user message exactly."
)

#: Guards against pathological inputs blowing up the context window.
MAX_COMMENT_CHARS = 4000
MAX_DIFF_CHARS = 12000
MAX_SUBSEQUENT_CHARS = 12000

_TRUNCATION_MARK = "\n... [truncated] ...\n"

#: ``Change_Until_Merged`` sentinel for a file deleted after the review.
DELETED_SENTINEL = "File_Deleted"


def _clip(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` characters, keeping head and tail."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.6)]
    tail = text[-int(limit * 0.4):]
    return head + _TRUNCATION_MARK + tail


def _field(value, fallback: str = "(not available)") -> str:
    """Render an optional field as prompt-ready text."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _json_literal(value) -> str:
    """Quote a value the way the appendix does before inlining it in a prompt.

    The appendix builds its prompts with ``json.dumps(value, ensure_ascii=False)``;
    mimicking that keeps newlines and quotes in comments and diffs from breaking
    the structure of the instruction.
    """
    if value is None:
        return json.dumps("", ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def describe_code_change(record: ReviewRecord) -> str:
    """Render the ``Subsequent Code Changes`` paragraph of the Stage-2 prompt.

    This mirrors ``describe_code_change`` from the appendix, whose four branches
    are: no change, the file was deleted, the file was renamed, and a normal
    cumulative diff.  The exact wording is reconstructed (the appendix function
    was not published verbatim); see ``docs/paper-deviations.md``.
    """
    changes = (record.subsequent_changes or "").strip()
    reviewed_path = (record.reviewed_path or "").strip()
    new_path = (record.new_path or "").strip()
    renamed = bool(reviewed_path and new_path and reviewed_path != new_path)

    if not changes:
        return "Subsequent Code Changes: No change happened after the review."
    if changes == DELETED_SENTINEL:
        return "Subsequent Code Changes: The reviewed file was deleted after the review."
    if renamed:
        return (
            "Subsequent Code Changes: The reviewed file was renamed to %s. "
            "The cumulative code changes are:\n%s" % (new_path, changes)
        )
    return "Subsequent Code Changes: The cumulative code changes are:\n%s" % changes


@dataclass(frozen=True)
class PromptTemplate:
    """One immutable template file."""

    name: str
    path: Path
    text: str
    digest: str

    def render(self, values: Dict[str, str]) -> str:
        """Substitute ``$placeholders``; unknown placeholders raise an error."""
        try:
            return Template(self.text).substitute(**values)
        except KeyError as exc:  # missing placeholder in the caller's mapping
            raise ConfigError(
                "prompt %s requires placeholder $%s which the pipeline does not "
                "provide" % (self.name, exc.args[0])
            )
        except ValueError as exc:  # dangling '$' in the template
            raise ConfigError("prompt %s contains an invalid '$': %s" % (self.name, exc))


def load_template(name: str, path) -> PromptTemplate:
    """Read a template file and fingerprint it."""
    template_path = Path(path)
    if not template_path.is_file():
        raise ConfigError("prompt template not found: %s" % template_path)
    text = template_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return PromptTemplate(name=name, path=template_path, text=text, digest=digest)


class PromptSet:
    """The two stage templates plus the version and answer format."""

    def __init__(
        self,
        stage1: PromptTemplate,
        stage2: PromptTemplate,
        version: str,
        output_format: str = "json",
    ):
        output_format = str(output_format or "json").strip().lower()
        if output_format not in OUTPUT_FORMATS:
            raise ConfigError(
                "unsupported prompts.format %r (expected one of %s)"
                % (output_format, ", ".join(OUTPUT_FORMATS))
            )
        self.stage1 = stage1
        self.stage2 = stage2
        self.version = version
        self.output_format = output_format

    @classmethod
    def load(cls, stage1_path, stage2_path, version: str, output_format: str = "json") -> "PromptSet":
        return cls(
            stage1=load_template("stage1", stage1_path),
            stage2=load_template("stage2", stage2_path),
            version=version,
            output_format=output_format,
        )

    @property
    def fingerprint(self) -> str:
        """Version + both digests; stored in every annotated row."""
        return "%s:%s:%s" % (self.version, self.stage1.digest, self.stage2.digest)

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT if self.output_format == "json" else SYSTEM_PROMPT_TEXT

    # ------------------------------------------------------------- rendering
    def _context(self, record: ReviewRecord, issues: Optional[List[str]] = None) -> Dict[str, str]:
        """All placeholder values either template family may reference."""
        items = list(issues or [])
        checklist = "\n".join("- %s" % item for item in items) if items else "(empty)"
        comment = _clip(record.comment_text, MAX_COMMENT_CHARS)
        diff = _clip(record.review_diff, MAX_DIFF_CHARS)
        subsequent = _clip(record.subsequent_changes, MAX_SUBSEQUENT_CHARS)
        return {
            # -- v1 (house style) placeholders
            "comment_text": comment,
            "review_diff": diff,
            "subsequent_changes": subsequent,
            "stage1_issues": checklist,
            "source": _field(record.source),
            "granularity": _field(record.granularity),
            "action_name": _field(record.action_name),
            "trigger": _field(record.trigger),
            "repo": _field(record.repo),
            # -- v2 (appendix style) placeholders
            "reviewed_path": _json_literal(_field(record.reviewed_path, "(unknown path)")),
            "reviewed_change": _json_literal(diff),
            "review_comment": _json_literal(comment),
            "review_comment_items": _json_literal(checklist),
            "subsequent_changes_block": describe_code_change(record),
        }

    def stage1_messages(self, record: ReviewRecord) -> List[Dict[str, str]]:
        """Build the chat messages for Stage-1 validity annotation."""
        content = self.stage1.render(self._context(record))
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]

    def stage2_messages(self, record: ReviewRecord, issues: List[str]) -> List[Dict[str, str]]:
        """Build the chat messages for Stage-2 adoption annotation."""
        content = self.stage2.render(self._context(record, issues))
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]

    def describe(self) -> str:
        return "prompts version=%s format=%s stage1=%s stage2=%s" % (
            self.version,
            self.output_format,
            self.stage1.digest,
            self.stage2.digest,
        )


__all__ = [
    "DELETED_SENTINEL",
    "OUTPUT_FORMATS",
    "PromptSet",
    "PromptTemplate",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_TEXT",
    "describe_code_change",
    "load_template",
]
