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
    parse_stage2,
)


def build_llm_client(config) -> LLMClient:
    """Instantiate the client selected by ``llm.provider``."""
    from ..errors import ConfigError

    provider = str(config.get("llm.provider")).lower()
    if provider == "mock":
        from .mock import MockLLMClient

        return MockLLMClient()
    if provider == "openai":
        from .client import OpenAIClient

        return OpenAIClient(
            api_key=config.api_key(),
            base_url=config.get("llm.base_url", None),
            timeout_s=float(config.get("llm.timeout_s", 60)),
        )
    raise ConfigError("unsupported llm.provider: %r" % provider)


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
    "parse_stage2",
    "build_llm_client",
]
