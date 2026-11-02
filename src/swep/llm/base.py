"""Provider-independent LLM abstractions.

The pipeline talks to :class:`LLMClient` only, which keeps three concerns
separate and testable:

* the real OpenAI-compatible client (:mod:`.client`),
* the offline mock used for development without credentials (:mod:`.mock`),
* the retry/caching/accounting wrapper owned by the pipeline.

``context`` on :meth:`LLMClient.complete` carries the structured record to
clients that need it (the mock derives deterministic labels from it).  Real
providers ignore it, so nothing about the prompt changes.  ``params`` carries
per-stage request overrides (for DeepSeek, "Stage-1 thinking off, Stage-2
thinking on") and is ignored by the mock.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Message = Dict[str, str]


@dataclass
class LLMResponse:
    """One completion plus the bookkeeping needed for cost reporting."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    request_id: str = ""
    finish_reason: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """Abstract chat-completion client."""

    name = "abstract"

    def complete(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0,
        max_output_tokens: int = 1024,
        context: Optional[dict] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Return one completion for ``messages``.

        Implementations raise :class:`swep.errors.LLMCallError` with the right
        ``retryable`` flag instead of leaking provider-specific exceptions.
        """
        raise NotImplementedError

    def close(self):
        """Release network resources; safe to call more than once."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
