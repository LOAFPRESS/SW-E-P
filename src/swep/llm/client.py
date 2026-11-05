"""Real provider client for any OpenAI-compatible chat-completions endpoint.

One client serves every hosted provider in :mod:`swep.providers`: OpenAI, DeepSeek
and Alibaba DashScope's compatible mode speak the same chat-completions protocol,
so only the base URL, the key and a few per-model parameters differ.

Provider quirks handled here, each one hit while preparing the reproduction:

1. **Reasoning models** (``o1*``, ``o3*``, ``o4*``) reject ``temperature`` and the
   legacy ``max_tokens``; they are called with ``max_completion_tokens`` and no
   temperature.  DeepSeek's current models instead toggle thinking with
   ``thinking: {type: enabled|disabled}`` (via ``extra_body``) or
   ``reasoning_effort``, keep ``max_tokens``, and ignore ``temperature`` — so
   thinking-mode requests also omit the temperature.  The paper reports
   ``temperature=0`` for both stages, which is recorded as a deviation (DOM-1.2)
   for the reasoning stages of this family.
2. Providers occasionally reject one parameter by name; the client retries once
   with the parameter repaired instead of failing the record.
3. Reasoning endpoints sometimes return the answer in ``reasoning_content`` with
   an empty ``content`` (DeepSeek R1 does this when the budget runs out); an empty
   answer is reported as a retryable failure rather than parsed into a wrong label.

API keys are passed only to the SDK constructor and are stripped from exception
text before it reaches logs (SEC-1.1/SEC-1.2).
"""

import time
from typing import Any, Dict, List, Optional, Set

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
        self._sdk_keys: Optional[Set[str]] = None

    # ------------------------------------------------------------------ call
    def complete(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0,
        max_output_tokens: int = 1024,
        context: Optional[dict] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        request = self._build_request(model, messages, temperature, max_output_tokens, params)
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
    @staticmethod
    def _thinking_enabled(model: str, extra: Dict[str, Any], extra_body: Optional[dict]) -> bool:
        """Whether the request will run in a provider "thinking"/reasoning mode.

        DeepSeek (2026-11 API) exposes three equivalent switches, in decreasing
        precedence: ``thinking: {type: enabled|disabled}`` (sent via ``extra_body``),
        ``reasoning_effort`` (``none`` disables it), and the ``o*`` model family.
        Thinking mode ignores ``temperature``, so we simply omit it.
        """
        body = extra_body if isinstance(extra_body, dict) else {}
        thinking = body.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type"):
            return str(thinking["type"]).lower() == "enabled"
        effort = str(extra.get("reasoning_effort") or "").lower()
        if effort:
            return effort != "none"
        return _is_reasoning_model(model)

    def _sdk_parameters(self) -> Set[str]:
        """Keyword arguments the installed SDK actually accepts on ``create()``.

        The SDK lags the providers: openai 1.55.3 has no ``reasoning_effort``
        keyword even though the APIs accept it.  Anything the SDK does not know
        is forwarded through ``extra_body``, which is serialised into the JSON
        request body verbatim, so both cases work without version sniffing.
        """
        if self._sdk_keys is None:
            try:
                import inspect

                self._sdk_keys = set(
                    inspect.signature(self._client.chat.completions.create).parameters
                )
            except (AttributeError, TypeError, ValueError):  # pragma: no cover - exotic SDKs
                self._sdk_keys = {"model", "messages", "temperature", "max_tokens",
                                  "max_completion_tokens", "extra_body"}
        return self._sdk_keys

    def _build_request(
        self,
        model: str,
        messages: List[Message],
        temperature: float,
        max_output_tokens: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Assemble the request, honouring per-model and per-stage overrides."""
        extra = dict(self._model_params.get(str(model), {}))
        if params:
            # Stage-level settings (e.g. Stage-1 thinking off, Stage-2 thinking on)
            # win over the model defaults; ``extra_body`` dicts are merged.
            body = extra.get("extra_body")
            stage_body = dict(params.get("extra_body") or {})
            base_body = dict(body) if isinstance(body, dict) else {}
            extra.update({k: v for k, v in params.items() if k != "extra_body"})
            if stage_body:
                base_body.update(stage_body)
                extra["extra_body"] = base_body
        body_overrides = dict(extra.pop("extra_body", None) or {})
        thinking = self._thinking_enabled(model, extra, body_overrides)
        request: Dict[str, Any] = {"model": model, "messages": messages}
        if _is_reasoning_model(model):
            # OpenAI's o* family renamed the output cap; DeepSeek/Qwen keep max_tokens.
            request["max_completion_tokens"] = int(max_output_tokens)
        else:
            request["max_tokens"] = int(max_output_tokens)
        if not thinking:
            request["temperature"] = float(temperature)
        sdk_keys = self._sdk_parameters()
        for key, value in extra.items():
            if key in sdk_keys:
                request[key] = value
            else:
                body_overrides[key] = value
        if body_overrides:
            merged = dict(request.get("extra_body") or {})
            merged.update(body_overrides)
            request["extra_body"] = merged
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
