"""LLM access layer: abstractions, provider clients, cache, retry, parsing."""

from .base import LLMClient, LLMResponse, Message  # noqa: F401
from .cache import ResponseCache  # noqa: F401
from .pricing import PriceTable  # noqa: F401
from .retry import RetryPolicy, call_with_retry  # noqa: F401
from .parsing import (  # noqa: F401
    Stage1Result,
    Stage2Result,
    extract_json_object,
    parse_stage1,
    parse_stage1_text,
    parse_stage2,
    parse_stage2_text,
    stage1_parser,
    stage2_parser,
)


def build_llm_client(config) -> LLMClient:
    """Instantiate the client selected by ``llm.provider``.

    Every hosted provider (OpenAI, DeepSeek, DashScope) speaks the
    OpenAI-compatible protocol, so they share one client class and differ only in
    their base URL and key variable -- both taken from :mod:`swep.providers`
    unless the YAML overrides them.
    """
    from ..errors import ConfigError
    from ..providers import KEYED_PROVIDERS

    provider = str(config.get("llm.provider")).lower()
    if provider == "mock":
        from .mock import MockLLMClient

        return MockLLMClient()
    if provider in KEYED_PROVIDERS:
        from .client import OpenAIClient

        return OpenAIClient(
            api_key=config.api_key(),
            base_url=config.effective_base_url() or None,
            timeout_s=float(config.get("llm.timeout_s", 60)),
            model_params=config.get("llm.model_params", {}) or {},
            provider=provider,
        )
    raise ConfigError(
        "unsupported llm.provider: %r (expected one of mock, %s)"
        % (provider, ", ".join(KEYED_PROVIDERS))
    )


__all__ = [
    "LLMClient",
    "LLMResponse",
    "Message",
    "ResponseCache",
    "PriceTable",
    "RetryPolicy",
    "call_with_retry",
    "Stage1Result",
    "Stage2Result",
    "extract_json_object",
    "parse_stage1",
    "parse_stage1_text",
    "parse_stage2",
    "parse_stage2_text",
    "stage1_parser",
    "stage2_parser",
    "build_llm_client",
]
