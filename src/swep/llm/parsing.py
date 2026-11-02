"""Parsing of model answers into typed annotation results.

Models are asked for bare JSON, but in practice they wrap it in markdown fences,
add a trailing sentence, or emit ``True`` instead of ``"Valid"``.  This module
is deliberately forgiving about *framing* and strict about *labels*: anything
that cannot be mapped onto the paper's label sets raises
:class:`swep.errors.ParseError`, which the pipeline may retry before recording a
warning (REQ-1.15).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ParseError
from ..schema import Stage1Label, Stage2Label

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_WS = re.compile(r"\s+")


def _candidate_blocks(text: str) -> List[str]:
    """Yield the substrings that could contain the JSON object, best first."""
    blocks = []
    if not text:
        return blocks
    for match in _FENCE.finditer(text):
        blocks.append(match.group(1).strip())
    blocks.append(text.strip())
    return blocks


def _balanced_object(text: str, start: int) -> Optional[str]:
    """Return the balanced ``{...}`` slice starting at ``start``, or ``None``."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start: index + 1]
    return None


def extract_json_object(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from an LLM answer."""
    for block in _candidate_blocks(text):
        start = block.find("{")
        while start != -1:
            candidate = _balanced_object(block, start)
            if candidate is not None:
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    start = block.find("{", start + 1)
                    continue
                if isinstance(parsed, dict):
                    return parsed
            start = block.find("{", start + 1)
    snippet = _WS.sub(" ", (text or "").strip())[:200]
    raise ParseError("no JSON object in model output: %r" % snippet)


def _as_list(value) -> List[str]:
    """Coerce a JSON value into a clean list of short strings."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip(" -*\t") for part in value.split("\n")]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    seen = set()
    cleaned = []
    for item in items:
        item = _WS.sub(" ", item).strip(" -*\t")
        if item and item.lower() not in ("none", "n/a", "[]", "") and item not in seen:
            seen.add(item)
            cleaned.append(item[:500])
    return cleaned


def _as_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return str(value).strip()


@dataclass
class Stage1Result:
    """Parsed Stage-1 answer."""

    label: Stage1Label
    issues: List[str] = field(default_factory=list)
    rationale: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.label is Stage1Label.VALID


@dataclass
class Stage2Result:
    """Parsed Stage-2 answer."""

    label: Stage2Label
    addressed_items: List[str] = field(default_factory=list)
    unaddressed_items: List[str] = field(default_factory=list)
    rationale: str = ""
    warnings: List[str] = field(default_factory=list)


def parse_stage1(text: str) -> Stage1Result:
    """Parse a Stage-1 answer into a :class:`Stage1Result`.

    Repair rules, each recorded in ``warnings``:

    * ``Valid`` without any issue -> the rationale is promoted to the single
      issue when it reads like a specification, otherwise the label is demoted
      to ``General`` (a Valid verdict must carry an actionable item).
    * ``None``/``General`` with issues present -> issues are dropped, because the
      exported checklist must be empty for those classes.
    """
    payload = extract_json_object(text)
    warnings: List[str] = []
    raw_label = payload.get("label", payload.get("stage1_label", payload.get("verdict")))
    if raw_label is None:
        raise ParseError("Stage-1 answer has no 'label' field: %r" % (payload,))
    try:
        label = Stage1Label.coerce(raw_label)
    except ValueError as exc:
        raise ParseError(str(exc))
    issues = _as_list(payload.get("issues", payload.get("issue_list")))
    rationale = _as_text(payload.get("rationale", payload.get("reasoning")))

    if label is Stage1Label.VALID and not issues:
        if len(rationale.split()) >= 6:
            issues = [_WS.sub(" ", rationale)[:500]]
            warnings.append("Valid without issues: rationale promoted to single issue")
        else:
            label = Stage1Label.GENERAL
            warnings.append("Valid without issues or usable rationale: demoted to General")
    if label is not Stage1Label.VALID and issues:
        warnings.append("%s carried %d issue(s): cleared" % (label.value, len(issues)))
        issues = []

    return Stage1Result(label=label, issues=issues, rationale=rationale, warnings=warnings)


def parse_stage2(text: str) -> Stage2Result:
    """Parse a Stage-2 answer into a :class:`Stage2Result`."""
    payload = extract_json_object(text)
    warnings: List[str] = []
    raw_label = payload.get("label", payload.get("stage2_label", payload.get("verdict")))
    if raw_label is None:
        raise ParseError("Stage-2 answer has no 'label' field: %r" % (payload,))
    try:
        label = Stage2Label.coerce(raw_label)
    except ValueError as exc:
        raise ParseError(str(exc))

    addressed = _as_list(payload.get("addressed_items", payload.get("addressed")))
    unaddressed = _as_list(payload.get("unaddressed_items", payload.get("unaddressed")))
    rationale = _as_text(payload.get("rationale", payload.get("reasoning")))

    if label is Stage2Label.FULLY and unaddressed:
        warnings.append("Fully but %d unaddressed item(s) listed" % len(unaddressed))
    if label is Stage2Label.UNADDRESSED and addressed:
        warnings.append("Unaddressed but %d addressed item(s) listed" % len(addressed))
    if label is Stage2Label.PARTIALLY and not (addressed and unaddressed):
        warnings.append("Partially without both sides populated")

    return Stage2Result(
        label=label,
        addressed_items=addressed,
        unaddressed_items=unaddressed,
        rationale=rationale,
        warnings=warnings,
    )


def parse_stage1_or_none(text: str) -> Tuple[Optional[Stage1Result], str]:
    """Non-throwing wrapper used by the mock/self-check paths."""
    try:
        return parse_stage1(text), ""
    except ParseError as exc:
        return None, str(exc)
