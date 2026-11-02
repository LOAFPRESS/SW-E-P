"""Offline, deterministic stand-in for the annotation LLM.

Why this exists: the Zenodo dataset and any provider credential were both
unavailable when the module was built, yet the pipeline (prompt building, retry,
caching, parsing, CSV export, evaluation) has to be exercised end to end.  The
mock implements the *interface*, not the paper's accuracy: it uses explicit
keyword heuristics for the sample comments and a hash-based fallback, so results
are reproducible but must never be reported as reproduction results.

``failures`` makes the client raise retryable errors on the first N calls, which
is how the retry/back-off path is demonstrated without a network.
"""

import hashlib
import json
import re
from typing import List, Optional

from ..errors import LLMCallError
from ..schema import ReviewRecord, Stage1Label, Stage2Label
from .base import LLMClient, LLMResponse, Message

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_BACKTICK = re.compile(r"`[^`]+`")
_WORD = re.compile(r"[A-Za-z0-9_]+")

_PRAISE = (
    "lgtm",
    "looks good",
    "looks great",
    "looks fine",
    "nice",
    "thanks",
    "thank you",
    "awesome",
    "ship it",
    "no issues",
    "well done",
    "good job",
)

_WEAK = (
    "improve",
    "improvement",
    "clean up",
    "cleaner",
    "readability",
    "consider",
    "could be",
    "maybe",
    "more tests",
    "add tests",
    "documentation",
    "better",
    "refactor",
    "needs work",
    "some work",
)

_STRONG = (
    "should",
    "must",
    "need to",
    "needs to",
    "fix",
    "remove",
    "rename",
    "replace",
    "avoid",
    "add",
    "missing",
    "unused",
    "null",
    "leak",
    "race",
    "typo",
    "duplicate",
    "hardcode",
    "hardcoded",
    "off-by-one",
    "validate",
    "raise",
    "close",
    "unchecked",
)


def _sentences(text: str) -> List[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def _is_actionable(sentence: str) -> bool:
    """A sentence is actionable when it names code and asks for a change."""
    lowered = sentence.lower()
    named_code = bool(_BACKTICK.search(sentence)) or bool(re.search(r"\b[a-z]+_[a-z_]+\b", sentence))
    has_strong = any(keyword in lowered for keyword in _STRONG)
    enough_words = len(_WORD.findall(sentence)) >= 5
    return has_strong and (enough_words or named_code)


def classify_comment(text: str) -> tuple:
    """Return ``(Stage1Label, issues, rationale)`` for a review comment."""
    sentences = _sentences(text)
    issues = [sentence for sentence in sentences if _is_actionable(sentence)]
    if issues:
        rationale = "The comment names a concrete problem and an expected change."
        return Stage1Label.VALID, issues[:3], rationale

    lowered = (text or "").lower()
    if any(keyword in lowered for keyword in _WEAK):
        return Stage1Label.GENERAL, [], "The comment asks for an improvement without naming what to change."
    if any(keyword in lowered for keyword in _PRAISE) or len(_WORD.findall(lowered)) <= 3:
        return Stage1Label.NONE, [], "The comment is praise or social talk and raises no issue."

    bucket = int(hashlib.sha256(lowered.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 60:
        return Stage1Label.NONE, [], "The comment describes the code without requesting a change."
    return Stage1Label.GENERAL, [], "The comment gestures at an issue that is not specific enough to act on."


def classify_adoption(record: ReviewRecord, issues: List[str]) -> tuple:
    """Return ``(Stage2Label, addressed, unaddressed, rationale)``."""
    subsequent = (record.subsequent_changes or "").strip()
    items = list(issues) or ["the requested change"]
    if not subsequent:
        return (
            Stage2Label.UNADDRESSED,
            [],
            items,
            "No subsequent modification touches the reviewed lines.",
        )
    lowered = subsequent.lower()
    if "deleted file" in lowered or "removed file" in lowered or "binary file" in lowered:
        return (
            Stage2Label.UNCERTAIN,
            [],
            [],
            "The reviewed file no longer exists in a comparable form.",
        )
    digest = hashlib.sha256((record.comment_id + "|" + "|".join(items)).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if len(items) == 1:
        # A one-item checklist can only be "fully" or "not at all" adopted.
        if bucket < 80:
            return Stage2Label.FULLY, items, [], "The requested item appears in the later diff."
        if bucket < 95:
            return Stage2Label.UNADDRESSED, [], items, "The later diff does not implement the request."
        return Stage2Label.UNCERTAIN, [], [], "The later diff is too small to judge adoption."
    if bucket < 50:
        return Stage2Label.FULLY, items, [], "Every requested item appears in the later diff."
    if bucket < 85:
        addressed = items[: max(1, len(items) // 2)]
        return (
            Stage2Label.PARTIALLY,
            addressed,
            items[len(addressed):],
            "Only part of the checklist appears in the later diff.",
        )
    if bucket < 95:
        return Stage2Label.UNADDRESSED, [], items, "The later diff touches the file but not the requested change."
    return Stage2Label.UNCERTAIN, [], [], "The later diff is too small to judge adoption."


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


class MockLLMClient(LLMClient):
    """Deterministic client that answers through the normal JSON contract."""

    name = "mock"

    def __init__(self, failures: Optional[List[str]] = None):
        self.failures = list(failures or [])
        self.calls = 0

    def complete(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0,
        max_output_tokens: int = 1024,
        context: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> LLMResponse:
        self.calls += 1
        if self.failures:
            kind = self.failures.pop(0)
            if kind == "timeout":
                raise LLMCallError("mock timeout", retryable=True)
            raise LLMCallError("mock rate limit", retryable=True, status_code=429)

        context = context or {}
        record: ReviewRecord = context.get("record")
        stage = context.get("stage", "stage1")
        if record is None:
            raise LLMCallError("MockLLMClient requires context['record']", retryable=False)

        if stage == "stage1":
            label, issues, rationale = classify_comment(record.comment_text)
            payload = {
                "label": label.value,
                "issues": issues,
                "rationale": rationale,
            }
        else:
            label, addressed, unaddressed, rationale = classify_adoption(
                record, context.get("issues") or []
            )
            payload = {
                "label": label.value,
                "addressed_items": addressed,
                "unaddressed_items": unaddressed,
                "rationale": rationale,
            }

        text = json.dumps(payload, ensure_ascii=False)
        prompt_chars = sum(len(message.get("content", "")) for message in messages)
        return LLMResponse(
            text=text,
            model=model,
            prompt_tokens=_estimate_tokens("x" * prompt_chars),
            completion_tokens=_estimate_tokens(text),
            latency_ms=0.0,
            cached=False,
            request_id="mock-%d" % self.calls,
            finish_reason="stop",
        )
