"""LLM providers reachable through the OpenAI-compatible protocol.

The appendix implementation (``call_llm/config.py`` + ``registry.py``) already
shows that the paper's experiments ran against several endpoints, including two
that are usable from mainland China: DeepSeek's native API and Alibaba
DashScope's OpenAI-compatible mode.  We keep that idea but express it as data,
so a new provider is a dictionary entry rather than a code change.

Only the *base URL* and the *environment variable holding the key* differ between
these providers; requests and responses follow the OpenAI chat-completions
shape, which is why one :class:`swep.llm.client.OpenAIClient` serves them all.

This module imports nothing heavy on purpose: ``swep.config`` validates the
provider name without importing the ``openai`` package, so an offline
``provider: mock`` run works even when the dependency is absent.
"""

from typing import Dict

#: ``provider -> {base_url, api_key_env, note}``.
PROVIDERS: Dict[str, Dict[str, str]] = {
    "mock": {
        "base_url": "",
        "api_key_env": "",
        "note": "offline deterministic stub; needs no key and spends nothing",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "note": "GPT-4.1 (Stage-1) and o3-mini (Stage-2) as in the paper",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "note": "deepseek-chat (V3) and deepseek-reasoner (R1); cheap, no GPT access needed",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "note": "Alibaba DashScope, OpenAI-compatible mode (e.g. qwen-plus / qwen-max)",
    },
}

#: Providers that require a key (everything except the offline stub).
KEYED_PROVIDERS = tuple(name for name in PROVIDERS if name != "mock")


def base_url(provider: str) -> str:
    """Default base URL of ``provider`` (empty for the mock provider)."""
    entry = PROVIDERS.get(str(provider).strip().lower())
    return entry["base_url"] if entry else ""


def api_key_env(provider: str) -> str:
    """Environment variable that holds the key of ``provider``."""
    entry = PROVIDERS.get(str(provider).strip().lower())
    return entry["api_key_env"] if entry else ""


__all__ = ["KEYED_PROVIDERS", "PROVIDERS", "api_key_env", "base_url"]
