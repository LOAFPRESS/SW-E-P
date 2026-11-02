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


def _stage1_from_payload(payload: Dict[str, Any]) -> Stage1Result:
    """Shared rules for a parsed Stage-1 payload (JSON answer or JSON-in-text)."""
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


def _stage2_from_payload(payload: Dict[str, Any]) -> Stage2Result:
    """Shared rules for a parsed Stage-2 payload (JSON answer or JSON-in-text)."""
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
    return _stage2_postprocess(label, addressed, unaddressed, rationale, warnings)


def _stage2_postprocess(
    label: Stage2Label,
    addressed: List[str],
    unaddressed: List[str],
    rationale: str,
    warnings: List[str],
) -> Stage2Result:
    """Consistency warnings shared by the JSON and the plain-text parsers."""
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


def parse_stage1(text: str) -> Stage1Result:
    """Parse a Stage-1 JSON answer into a :class:`Stage1Result`.

    Repair rules, each recorded in ``warnings``:

    * ``Valid`` without any issue -> the rationale is promoted to the single
      issue when it reads like a specification, otherwise the label is demoted
      to ``General`` (a Valid verdict must carry an actionable item).
    * ``None``/``General`` with issues present -> issues are dropped, because the
      exported checklist must be empty for those classes.
    """
    return _stage1_from_payload(extract_json_object(text))


def parse_stage2(text: str) -> Stage2Result:
    """Parse a Stage-2 JSON answer into a :class:`Stage2Result`."""
    return _stage2_from_payload(extract_json_object(text))


# --------------------------------------------------------------- plain text
#: Appendix Stage-1 classifications, in the order the appendix matches them.
_STAGE1_TEXT_LABELS = (
    ("not contain any issues or suggestions", Stage1Label.NONE),
    ("not contain any items", Stage1Label.NONE),
    ("only contain general issues or suggestions", Stage1Label.GENERAL),
    ("only contain general items", Stage1Label.GENERAL),
    ("not contain specific items", Stage1Label.GENERAL),
    ("contain valid issues or suggestions", Stage1Label.VALID),
    ("contain valid items", Stage1Label.VALID),
)

#: Appendix Stage-2 classifications, matched by earliest occurrence after the
#: ``Classification:`` marker (the appendix uses exactly this rule).
_STAGE2_TEXT_LABELS = (
    ("not enough information", Stage2Label.UNCERTAIN),
    ("not addressed", Stage2Label.UNADDRESSED),
    ("partly addressed", Stage2Label.PARTIALLY),
    ("partially addressed", Stage2Label.PARTIALLY),
    ("fully addressed", Stage2Label.FULLY),
)

_ITEM_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s*")


def _after_marker(low: str, marker: str) -> Optional[int]:
    """Index just past the last occurrence of ``marker``, or ``None``."""
    index = low.rfind(marker)
    return None if index == -1 else index + len(marker)


def _tail(text: str, marker: str) -> Optional[str]:
    """Everything after the last ``marker`` (case-insensitive), or ``None``."""
    index = _after_marker(text.lower(), marker)
    return None if index is None else text[index:]


def _earliest_match(low: str, options) -> Optional[Any]:
    """Return the value whose phrase occurs first in ``low``."""
    best_index = -1
    best_value = None
    for phrase, value in options:
        index = low.find(phrase)
        if index == -1:
            continue
        if best_index == -1 or index < best_index:
            best_index = index
            best_value = value
    return best_value


def split_items(block: str) -> List[str]:
    """Split a free-text item list into clean, de-duplicated strings."""
    items: List[str] = []
    seen = set()
    for line in (block or "").splitlines():
        candidate = _ITEM_BULLET.sub("", line).strip()
        candidate = _WS.sub(" ", candidate)
        if not candidate or candidate.lower() in ("none", "n/a", "(empty)"):
            continue
        if candidate not in seen:
            seen.add(candidate)
            items.append(candidate[:500])
    return items


def _section(text: str, start_marker: str, end_markers) -> str:
    """Slice the text between two markers (case-insensitive)."""
    low = text.lower()
    start = _after_marker(low, start_marker)
    if start is None:
        return ""
    end = len(text)
    for marker in end_markers:
        index = low.find(marker, start)
        if index != -1 and index < end:
            end = index
    return text[start:end]


def _header_after(low: str, marker: str, not_preceded_by: str = "") -> Optional[int]:
    """Index just past the first ``marker`` that is not part of a longer word.

    ``"unaddressed items:"`` contains ``"addressed items:"``, so a plain
    ``find``/``rfind`` would slice from the wrong heading.
    """
    start = 0
    while True:
        index = low.find(marker, start)
        if index == -1:
            return None
        if not not_preceded_by or not low[:index].endswith(not_preceded_by):
            return index + len(marker)
        start = index + len(marker)


#: Answers the appendix returns verbatim, without a ``Classification:`` line.
_STAGE2_SHORT_CIRCUIT = (
    ("no change happened", Stage2Label.UNADDRESSED),
    ("remains unaddressed", Stage2Label.UNADDRESSED),
    ("remaining unaddressed", Stage2Label.UNADDRESSED),
)


def parse_stage1_text(text: str) -> Stage1Result:
    """Parse the appendix's plain-text Stage-1 answer.

    Accepted shape (from ``extract_suggestion_prompter_3.py``)::

        Issues or Suggestions:
        - item
        Classification: Contain Valid Issues Or Suggestions

    A model that answers with JSON anyway is accepted through the JSON rules,
    because rejecting a correct answer would waste a paid call.
    """
    try:
        return _stage1_from_payload(extract_json_object(text))
    except ParseError:
        pass

    if not str(text or "").strip():
        raise ParseError("empty Stage-1 answer")

    low = text.lower()
    body = _tail(text, "classification:") if "classification:" in low else text
    label = _earliest_match(body.lower(), _STAGE1_TEXT_LABELS)
    if label is None:
        snippet = _WS.sub(" ", text.strip())[:200]
        raise ParseError("Stage-1 answer has no recognisable Classification: %r" % snippet)

    issues_block = _section(text, "issues or suggestions:", ("classification:",))
    issues = split_items(issues_block)
    rationale = _WS.sub(" ", issues_block).strip()
    return _stage1_from_payload({"label": label.value, "issues": issues, "rationale": rationale})


def parse_stage2_text(text: str) -> Stage2Result:
    """Parse the appendix's plain-text Stage-2 answer.

    Accepted shape (from ``analyze_addressed_prompter_4.py``)::

        Analysis details:
        - Addressed Items:
        - item
        - Unaddressed Items:
        - item
        Classification: Fully Addressed
    """
    try:
        return _stage2_from_payload(extract_json_object(text))
    except ParseError:
        pass

    if not str(text or "").strip():
        raise ParseError("empty Stage-2 answer")

    low = text.lower()
    if "classification:" in low:
        body = _tail(text, "classification:")
    else:
        for phrase, value in _STAGE2_SHORT_CIRCUIT:
            if phrase in low:
                rationale = _WS.sub(" ", text.strip())
                return _stage2_postprocess(value, [], [], rationale, [])
        body = text
    label = _earliest_match(body.lower(), _STAGE2_TEXT_LABELS)
    if label is None:
        snippet = _WS.sub(" ", text.strip())[:200]
        raise ParseError("Stage-2 answer has no recognisable Classification: %r" % snippet)

    analysis = _section(text, "analysis details:", ("classification:",)) or text
    low_analysis = analysis.lower()
    unaddressed_at = low_analysis.find("unaddressed items:")
    addressed_at = _header_after(low_analysis, "addressed items:", not_preceded_by="un")

    addressed_block = ""
    if addressed_at is not None:
        end = unaddressed_at if unaddressed_at > addressed_at else len(analysis)
        addressed_block = analysis[addressed_at:end]
    unaddressed_block = ""
    if unaddressed_at != -1:
        unaddressed_block = analysis[unaddressed_at + len("unaddressed items:"):]

    addressed = split_items(addressed_block)
    unaddressed = split_items(unaddressed_block)
    rationale = _WS.sub(" ", analysis).strip()
    return _stage2_postprocess(label, addressed, unaddressed, rationale, [])


def stage1_parser(output_format: str):
    """Pick the Stage-1 parser for the configured answer format."""
    return parse_stage1 if str(output_format).lower() == "json" else parse_stage1_text


def stage2_parser(output_format: str):
    """Pick the Stage-2 parser for the configured answer format."""
    return parse_stage2 if str(output_format).lower() == "json" else parse_stage2_text


def parse_stage1_or_none(text: str) -> Tuple[Optional[Stage1Result], str]:
    """Non-throwing wrapper used by the mock/self-check paths."""
    try:
        return parse_stage1(text), ""
    except ParseError as exc:
        return None, str(exc)
