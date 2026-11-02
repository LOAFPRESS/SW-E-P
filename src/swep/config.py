"""Configuration loading, merging with defaults, and validation.

Design rules (REQ-1.2, REQ-1.3, SEC-1.1):

* Nothing about models, paths, retry policy or budget is hard-coded in the
  pipeline; every such value comes from the YAML file.
* Relative paths are resolved against the *project root*, defined as the parent
  of the directory holding the YAML file when that directory is called
  ``config`` (the default layout), otherwise the YAML file's own directory.
* Environment variables are expanded with the ``${VAR}`` syntax, so no secret
  ever needs to appear in the file.
* Validation happens once, at load time, and reports the offending key.
"""

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml

from .errors import ConfigError

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_MISSING = object()

#: Baseline configuration.  A user YAML only overrides what it declares.
DEFAULTS: Dict[str, Any] = {
    "run": {
        "name": "gold150",
        "limit": None,
        "seed": 42,
        "abort_on_record_error": False,
        "log_level": "INFO",
    },
    "data": {
        "path": None,
        "format": "auto",
        "column_map": {},
        "split": None,
        "require_nonempty": ["comment_text"],
    },
    "llm": {
        "provider": "mock",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "stage1_model": "gpt-4.1",
        "stage2_model": "o3-mini",
        "temperature": 0,
        "max_output_tokens": 1024,
        "timeout_s": 60,
        "retry": {
            "max_attempts": 5,
            "base_delay_s": 2.0,
            "max_delay_s": 60.0,
            "jitter_s": 0.5,
        },
        "budget": {
            "max_usd": 5.0,
            "prices_per_1m_tokens": {
                "gpt-4.1": {"input": 2.0, "output": 8.0},
                "o3-mini": {"input": 1.1, "output": 4.4},
            },
            "default_price": {"input": 2.0, "output": 8.0},
        },
        "cache": {"enabled": True, "path": "artifacts/cache.sqlite3"},
        "max_parse_retries": 2,
    },
    "prompts": {
        "stage1": "prompts/stage1.md",
        "stage2": "prompts/stage2.md",
        "version": "v1-reconstructed-2026-11",
    },
    "output": {
        "dir": "artifacts",
        "annotations_csv": "annotations.csv",
        "requests_jsonl": "requests.jsonl",
        "summary_json": "summary.json",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_env(value: Any) -> Any:
    """Expand ``${VAR}`` occurrences in every string of a nested structure."""

    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(
                    "configuration references undefined environment variable "
                    "${%s}; export it before running" % name
                )
            return os.environ[name]

        return _ENV_PATTERN.sub(replace, value)
    return value


class Config:
    """Validated view over the merged configuration."""

    def __init__(self, raw: Dict[str, Any], path: Path):
        self.raw = raw
        self.path = Path(path).resolve()
        self.root = self._infer_root(self.path)

    @staticmethod
    def _infer_root(config_path: Path) -> Path:
        parent = config_path.parent
        if parent.name.lower() in ("config", "conf", "configs"):
            return parent.parent
        return parent

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path) -> "Config":
        config_path = Path(path)
        if not config_path.is_file():
            raise ConfigError("configuration file not found: %s" % config_path)
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ConfigError("cannot parse YAML in %s: %s" % (config_path, exc))
        if not isinstance(loaded, dict):
            raise ConfigError("top level of %s must be a mapping" % config_path)
        merged = _deep_merge(DEFAULTS, loaded)
        merged = _expand_env(merged)
        config = cls(merged, config_path)
        config._validate()
        return config

    # -------------------------------------------------------------- access
    def get(self, dotted: str, default: Any = _MISSING) -> Any:
        """Read a dotted key, e.g. ``config.get("llm.retry.max_attempts")``."""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise ConfigError("missing configuration key: %s" % dotted)
                return default
            node = node[part]
        return node

    def resolve(self, value: Any) -> Path:
        """Resolve a path value against the project root."""
        if value is None:
            raise ConfigError("expected a path, got null")
        candidate = Path(str(value)).expanduser()
        return candidate if candidate.is_absolute() else (self.root / candidate)

    def api_key(self) -> str:
        """Return the API key from the environment.

        The key is never written to disk, logs or exception messages; when it is
        missing the error names the expected variable (SEC-1.1).
        """
        env_name = self.get("llm.api_key_env", "OPENAI_API_KEY")
        value = os.environ.get(env_name, "").strip()
        if not value:
            raise ConfigError(
                "LLM provider 'openai' requires the environment variable %s to be "
                "set; alternatively set llm.provider: mock to run offline" % env_name
            )
        return value

    # ------------------------------------------------------------ validation
    def _validate(self):
        """Fail fast on structural problems, naming the offending key."""
        checks = [
            ("run.limit", (type(None), int), "an integer or null"),
            ("run.seed", (int,), "an integer"),
            ("data.path", (type(None), str), "a path string (or null when --dataset is used)"),
            ("data.format", (str,), "one of auto/jsonl/json/csv"),
            ("llm.provider", (str,), "one of mock/openai"),
            ("llm.stage1_model", (str,), "a model name"),
            ("llm.stage2_model", (str,), "a model name"),
            ("llm.temperature", (int, float), "a number"),
            ("llm.max_output_tokens", (int,), "an integer"),
            ("llm.retry.max_attempts", (int,), "an integer >= 1"),
            ("llm.retry.base_delay_s", (int, float), "a number >= 0"),
            ("llm.retry.max_delay_s", (int, float), "a number >= base_delay_s"),
            ("llm.cache.enabled", (bool,), "true or false"),
            ("llm.cache.path", (str,), "a path string"),
            ("prompts.stage1", (str,), "a path string"),
            ("prompts.stage2", (str,), "a path string"),
            ("prompts.version", (str,), "a version string"),
            ("output.dir", (str,), "a path string"),
        ]
        for dotted, types, expected in checks:
            value = self.get(dotted)
            if not isinstance(value, types) or isinstance(value, bool) and bool not in types:
                raise ConfigError(
                    "configuration key %s must be %s, got %r" % (dotted, expected, value)
                )

        if self.get("llm.provider") not in ("mock", "openai"):
            raise ConfigError(
                "llm.provider must be 'mock' or 'openai', got %r"
                % (self.get("llm.provider"),)
            )
        if self.get("data.format") not in ("auto", "jsonl", "json", "csv"):
            raise ConfigError(
                "data.format must be one of auto/jsonl/json/csv, got %r"
                % (self.get("data.format"),)
            )
        if not 0 <= float(self.get("llm.temperature")) <= 2:
            raise ConfigError("llm.temperature must lie within [0, 2]")
        if self.get("llm.retry.max_attempts") < 1:
            raise ConfigError("llm.retry.max_attempts must be >= 1")
        if self.get("llm.retry.max_delay_s") < self.get("llm.retry.base_delay_s"):
            raise ConfigError("llm.retry.max_delay_s must be >= llm.retry.base_delay_s")

        budget = self.get("llm.budget.max_usd", None)
        if budget is not None and not isinstance(budget, (int, float)):
            raise ConfigError("llm.budget.max_usd must be a number or null")
        if budget is not None and budget <= 0:
            raise ConfigError("llm.budget.max_usd must be positive")

        if self.get("data.column_map") is None:
            self.raw["data"]["column_map"] = {}
        if not isinstance(self.get("data.column_map"), dict):
            raise ConfigError("data.column_map must be a mapping of target -> source column")

        for key in ("prompts.stage1", "prompts.stage2"):
            prompt_path = self.resolve(self.get(key))
            if not prompt_path.is_file():
                raise ConfigError(
                    "prompt template for %s not found: %s" % (key.split(".")[-1], prompt_path)
                )

    # -------------------------------------------------------------- helpers
    def output_dir(self) -> Path:
        return self.resolve(self.get("output.dir"))

    def describe(self) -> str:
        """One-line, secret-free description printed at run start."""
        return (
            "provider=%s stage1=%s stage2=%s temperature=%s prompt_version=%s"
            % (
                self.get("llm.provider"),
                self.get("llm.stage1_model"),
                self.get("llm.stage2_model"),
                self.get("llm.temperature"),
                self.get("prompts.version"),
            )
        )
