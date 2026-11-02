"""Real provider client for any OpenAI-compatible chat-completions endpoint.

One client serves every hosted provider in :mod:`swep.providers`: OpenAI, DeepSeek
and Alibaba DashScope's compatible mode speak the same chat-completions protocol,
so only the base URL, the key and a few per-model parameters differ.

Provider quirks handled here, each one hit while preparing the reproduction:

1. **Reasoning models** (``o1*``, ``o3*``, ``o4*`` and anything configured with a
   ``reasoning_effort`` parameter) reject ``temperature`` and the legacy
   ``max_tokens`` parameter; they are called with ``max_completion_tokens`` and no
   temperature.  The paper reports ``temperature=0`` for both stages, which is
   recorded as a deviation (DOM-1.2) for Stage-2 models of this family.
2. Providers occasionally reject one parameter by name; the client retries once
   with the parameter repaired instead of failing the record.
3. Reasoning endpoints sometimes return the answer in ``reasoning_content`` with
   an empty ``content`` (DeepSeek R1 does this when the budget runs out); an empty
   answer is reported as a retryable failure rather than parsed into a wrong label.

API keys are passed only to the SDK constructor and are stripped from exception
text before it reaches logs (SEC-1.1/SEC-1.2).
"""

import time
from typing import Any, Dict, List, Optional

from ..errors import ConfigError, LLMCallError
from ..logging_utils import get_logger
from .base import LLMClient, LLMResponse, Message

_REASONING_PREFIXES = ("o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    name = str(model or "").lower()
    return name.startswith(_REASONING_PREFIXES)


class OpenAIClient(LLMClient):
    """Chat-completions client over the official ``openai`` SDK."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout_s: float = 60.0,
        model_params: Optional[Dict[str, Dict[str, Any]]] = None,
        provider: str = "openai",
    ):
        if not api_key:
            raise ConfigError("OpenAIClient requires a non-empty API key")
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ConfigError(
                "the 'openai' package is required for a hosted llm.provider: %s" % exc
            )
        self._openai = openai
        self._api_key = api_key
        self.name = provider
        self._model_params = {
            str(model): dict(params or {})
            for model, params in (model_params or {}).items()
            if isinstance(params, dict)
        }
        client_kwargs = {"api_key": api_key, "timeout": float(timeout_s)}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**client_kwargs)

    # ------------------------------------------------------------------ call
    def complete(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0,
        max_output_tokens: int = 1024,
        context: Optional[dict] = None,
    ) -> LLMResponse:
        request = self._build_request(model, messages, temperature, max_output_tokens)
        started = time.perf_counter()
        response = self._create(request)
        latency_ms = (time.perf_counter() - started) * 1000.0

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        choice = response.choices[0] if getattr(response, "choices", None) else None
        text = ""
        finish_reason = ""
        if choice is not None:
            message = choice.message
            text = (getattr(message, "content", None) or "").strip()
            if not text:
                # DeepSeek R1 / other reasoning endpoints may only fill this one.
                text = (getattr(message, "reasoning_content", None) or "").strip()
            finish_reason = getattr(choice, "finish_reason", "") or ""

        if not text:
            raise LLMCallError(
                "provider returned an empty answer (finish_reason=%r); treating as a "
                "retryable failure instead of parsing it" % (finish_reason,),
                retryable=True,
            )

        return LLMResponse(
            text=text,
            model=str(getattr(response, "model", model) or model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cached=False,
            request_id=str(getattr(response, "id", "") or ""),
            finish_reason=finish_reason,
        )

    # --------------------------------------------------------------- helpers
    def _build_request(
        self, model: str, messages: List[Message], temperature: float, max_output_tokens: int
    ) -> dict:
        """Assemble the request, honouring per-model parameter overrides."""
        extra = self._model_params.get(str(model), {})
        reasoning = _is_reasoning_model(model) or "reasoning_effort" in extra
        request: Dict[str, Any] = {"model": model, "messages": messages}
        if reasoning:
            request["max_completion_tokens"] = int(max_output_tokens)
        else:
            request["temperature"] = float(temperature)
            request["max_tokens"] = int(max_output_tokens)
        for key, value in extra.items():
            request[key] = value
        return request

    def _create(self, request: dict):
        """Call the API, repairing one rejected parameter when needed."""
        try:
            return self._client.chat.completions.create(**request)
        except Exception as exc:  # noqa: BLE001 - translated below
            repaired = self._repair(request, exc)
            if repaired is None:
                raise self._translate(exc)
            get_logger().warning(
                "provider rejected a parameter (%s); retrying with %s",
                self._sanitize(str(exc))[:120],
                sorted(set(repaired) - set(request)) or "removed parameter",
            )
            try:
                return self._client.chat.completions.create(**repaired)
            except Exception as exc2:  # noqa: BLE001
                raise self._translate(exc2)

    @staticmethod
    def _repair(request: dict, exc: Exception) -> Optional[dict]:
        """Return a patched request for known parameter-rejection errors.

        The branches are mutually exclusive: OpenAI's message for a legacy model
        mentions *both* token parameters ("unsupported 'max_tokens' ... use
        'max_completion_tokens'"), so applying two independent fixes would swap
        the parameter back and forth and send neither.
        """
        message = str(exc).lower()
        repaired = dict(request)
        changed = False
        if "temperature" in message and "unsupported" in message:
            repaired.pop("temperature", None)
            changed = True
        if "max_tokens" in message or "max_completion_tokens" in message:
            if "max_completion_tokens" in message:
                # Prefer the modern parameter: the message says it is the one
                # to use, either because max_tokens is legacy or because
                # max_completion_tokens is the supported spelling.
                if "max_tokens" in repaired:
                    repaired["max_completion_tokens"] = repaired.pop("max_tokens")
                    changed = True
            elif "max_tokens" in repaired:
                repaired["max_completion_tokens"] = repaired.pop("max_tokens")
                changed = True
            elif "max_completion_tokens" in repaired:
                repaired["max_tokens"] = repaired.pop("max_completion_tokens")
                changed = True
        return repaired if changed else None

    def _translate(self, exc: Exception) -> LLMCallError:
        """Map a provider exception onto ``LLMCallError`` with a retry flag."""
        openai = self._openai
        text = self._sanitize(str(exc))
        status = getattr(exc, "status_code", None)
        if isinstance(exc, getattr(openai, "AuthenticationError", ())):
            return LLMCallError("authentication failed: %s" % text, retryable=False, status_code=401)
        if isinstance(exc, getattr(openai, "PermissionDeniedError", ())):
            return LLMCallError("permission denied: %s" % text, retryable=False, status_code=403)
        if isinstance(exc, getattr(openai, "NotFoundError", ())):
            return LLMCallError("model or endpoint not found: %s" % text, retryable=False, status_code=404)
        if isinstance(exc, getattr(openai, "BadRequestError", ())):
            return LLMCallError("invalid request: %s" % text, retryable=False, status_code=400)
        if isinstance(exc, getattr(openai, "RateLimitError", ())):
            return LLMCallError("rate limited: %s" % text, retryable=True, status_code=429)
        if isinstance(exc, (getattr(openai, "APITimeoutError", ()), getattr(openai, "APIConnectionError", ()))):
            return LLMCallError("transport failure: %s" % text, retryable=True)
        if isinstance(exc, getattr(openai, "InternalServerError", ())):
            return LLMCallError("provider error: %s" % text, retryable=True, status_code=500)
        retryable = isinstance(status, int) and (status == 429 or status >= 500)
        return LLMCallError("LLM call failed: %s" % text, retryable=retryable, status_code=status)

    def _sanitize(self, text: str) -> str:
        """Remove the API key from provider error text (SEC-1.2)."""
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***")
        return text

    def close(self):
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
