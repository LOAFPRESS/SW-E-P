"""Prompt template loading, rendering and versioning.

The paper ships its prompts only in the Zenodo supplementary material, which
was unreachable when this module was written; the templates here are a faithful
*reconstruction* of the annotation rules described in Section IV-B of the
paper.  Every change to a template must bump ``prompts.version`` in the YAML
configuration and be recorded in ``prompts/CHANGELOG.md`` so that the deviation
log required by DOM-1.2 stays accurate.

Templates use :class:`string.Template` placeholders such as ``$comment_text``;
values are inserted verbatim, so no escaping of braces inside diffs is needed.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..errors import ConfigError
from ..schema import ReviewRecord
from string import Template

#: System message shared by both stages.  Keeping it short leaves room for the
#: (much longer) review context in the user message.
SYSTEM_PROMPT = (
    "You are a meticulous software engineering researcher. "
    "Answer with a single JSON object and no additional text."
)

#: Guards against pathological inputs blowing up the context window.
MAX_COMMENT_CHARS = 4000
MAX_DIFF_CHARS = 12000
MAX_SUBSEQUENT_CHARS = 12000

_TRUNCATION_MARK = "\n... [truncated] ...\n"


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
    """The two stage templates plus the version string from the configuration."""

    def __init__(self, stage1: PromptTemplate, stage2: PromptTemplate, version: str):
        self.stage1 = stage1
        self.stage2 = stage2
        self.version = version

    @classmethod
    def load(cls, stage1_path, stage2_path, version: str) -> "PromptSet":
        return cls(
            stage1=load_template("stage1", stage1_path),
            stage2=load_template("stage2", stage2_path),
            version=version,
        )

    @property
    def fingerprint(self) -> str:
        """Version + both digests; stored in every annotated row."""
        return "%s:%s:%s" % (self.version, self.stage1.digest, self.stage2.digest)

    # ------------------------------------------------------------- rendering
    def stage1_messages(self, record: ReviewRecord) -> List[Dict[str, str]]:
        """Build the chat messages for Stage-1 validity annotation."""
        content = self.stage1.render(
            {
                "comment_text": _clip(record.comment_text, MAX_COMMENT_CHARS),
                "review_diff": _clip(record.review_diff, MAX_DIFF_CHARS),
                "source": _field(record.source),
                "granularity": _field(record.granularity),
                "action_name": _field(record.action_name),
                "trigger": _field(record.trigger),
                "repo": _field(record.repo),
            }
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    def stage2_messages(self, record: ReviewRecord, issues: List[str]) -> List[Dict[str, str]]:
        """Build the chat messages for Stage-2 adoption annotation."""
        checklist = "\n".join("- %s" % item for item in issues) if issues else "(empty)"
        content = self.stage2.render(
            {
                "comment_text": _clip(record.comment_text, MAX_COMMENT_CHARS),
                "stage1_issues": checklist,
                "review_diff": _clip(record.review_diff, MAX_DIFF_CHARS),
                "subsequent_changes": _clip(
                    record.subsequent_changes, MAX_SUBSEQUENT_CHARS
                ),
                "source": _field(record.source),
                "granularity": _field(record.granularity),
                "action_name": _field(record.action_name),
                "repo": _field(record.repo),
            }
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    def describe(self) -> str:
        return "prompts version=%s stage1=%s stage2=%s" % (
            self.version,
            self.stage1.digest,
            self.stage2.digest,
        )


__all__ = [
    "PromptSet",
    "PromptTemplate",
    "SYSTEM_PROMPT",
    "load_template",
]
