"""Tests for configuration loading, validation and secrets handling."""

import pytest
import yaml

from swep.config import Config
from swep.errors import ConfigError


def _write(tmp_path, payload):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def _deep(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep(merged[key], value)
        else:
            merged[key] = value
    return merged


@pytest.fixture
def make_config(tmp_path):
    """Load a configuration whose prompt files exist next to it."""
    prompts = tmp_path / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "stage1.md").write_text("stage1 $comment_text", encoding="utf-8")
    (prompts / "stage2.md").write_text("stage2 $comment_text $stage1_issues", encoding="utf-8")

    def _make(payload=None):
        base = {"prompts": {"stage1": "prompts/stage1.md", "stage2": "prompts/stage2.md"}}
        return Config.load(_write(tmp_path, _deep(base, payload or {})))

    return _make


class TestDefaultsAndMerging:
    def test_missing_sections_fall_back_to_defaults(self, make_config):
        config = make_config()
        assert config.get("llm.provider") == "mock"
        assert config.get("llm.retry.max_attempts") == 5
        assert config.get("llm.temperature") == 0

    def test_user_values_override_defaults(self, make_config):
        config = make_config(
            {"llm": {"stage1_model": "custom-model", "retry": {"max_attempts": 2}}}
        )
        assert config.get("llm.stage1_model") == "custom-model"
        assert config.get("llm.retry.max_attempts") == 2
        # untouched siblings survive the merge
        assert config.get("llm.retry.base_delay_s") == 2.0

    def test_get_reports_missing_keys(self, make_config):
        config = make_config()
        with pytest.raises(ConfigError):
            config.get("llm.does.not.exist")
        assert config.get("llm.does.not.exist", "fallback") == "fallback"


class TestPathResolution:
    def test_relative_paths_resolve_against_the_config_directory_parent(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "stage1.md").write_text("s1", encoding="utf-8")
        (prompts / "stage2.md").write_text("s2", encoding="utf-8")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        path = config_dir / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "output": {"dir": "artifacts"},
                    "prompts": {"stage1": "prompts/stage1.md", "stage2": "prompts/stage2.md"},
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        config = Config.load(path)
        assert config.root == tmp_path
        assert config.output_dir() == tmp_path / "artifacts"

    def test_absolute_paths_are_kept(self, make_config, tmp_path):
        target = tmp_path / "elsewhere"
        config = make_config({"output": {"dir": str(target)}})
        assert config.output_dir() == target


class TestEnvironmentExpansion:
    def test_environment_variables_are_expanded(self, make_config, monkeypatch):
        monkeypatch.setenv("SWEP_TEST_DIR", "expanded-out")
        config = make_config({"output": {"dir": "${SWEP_TEST_DIR}"}})
        assert config.get("output.dir") == "expanded-out"

    def test_missing_variable_fails_with_the_variable_name(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SWEP_TEST_ABSENT", raising=False)
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "stage1.md").write_text("s1", encoding="utf-8")
        (prompts / "stage2.md").write_text("s2", encoding="utf-8")
        with pytest.raises(ConfigError) as excinfo:
            Config.load(
                _write(
                    tmp_path,
                    {
                        "output": {"dir": "${SWEP_TEST_ABSENT}"},
                        "prompts": {"stage1": "prompts/stage1.md", "stage2": "prompts/stage2.md"},
                    },
                )
            )
        assert "SWEP_TEST_ABSENT" in str(excinfo.value)


class TestApiKey:
    def test_key_is_read_from_the_configured_variable(self, make_config, monkeypatch):
        monkeypatch.setenv("SWEP_KEY", "sk-secret-value")
        config = make_config({"llm": {"provider": "openai", "api_key_env": "SWEP_KEY"}})
        assert config.api_key() == "sk-secret-value"

    def test_missing_key_mentions_the_variable_and_the_mock_option(self, make_config, monkeypatch):
        monkeypatch.delenv("SWEP_MISSING_KEY", raising=False)
        config = make_config({"llm": {"provider": "openai", "api_key_env": "SWEP_MISSING_KEY"}})
        with pytest.raises(ConfigError) as excinfo:
            config.api_key()
        message = str(excinfo.value)
        assert "SWEP_MISSING_KEY" in message
        assert "mock" in message


class TestValidation:
    @pytest.mark.parametrize(
        "payload,fragment",
        [
            ({"llm": {"provider": "anthropic"}}, "llm.provider"),
            ({"llm": {"temperature": 5}}, "llm.temperature"),
            ({"llm": {"retry": {"max_attempts": 0}}}, "llm.retry.max_attempts"),
            ({"llm": {"retry": {"base_delay_s": 10, "max_delay_s": 1}}}, "max_delay_s"),
            ({"data": {"format": "xlsx"}}, "data.format"),
            ({"llm": {"budget": {"max_usd": -1}}}, "llm.budget.max_usd"),
        ],
    )
    def test_invalid_values_are_rejected_by_name(self, make_config, payload, fragment):
        with pytest.raises(ConfigError) as excinfo:
            make_config(payload)
        assert fragment in str(excinfo.value)

    def test_missing_prompt_file_is_reported(self, tmp_path):
        with pytest.raises(ConfigError) as excinfo:
            Config.load(
                _write(
                    tmp_path,
                    {"prompts": {"stage1": "missing/stage1.md", "stage2": "missing/stage2.md"}},
                )
            )
        assert "prompt template" in str(excinfo.value)

    def test_missing_configuration_file(self, tmp_path):
        with pytest.raises(ConfigError):
            Config.load(tmp_path / "nope.yaml")

    def test_unparsable_yaml(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("llm: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigError):
            Config.load(path)

    def test_describe_never_contains_a_secret(self, make_config, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-do-not-print")
        config = make_config({"llm": {"provider": "openai"}})
        assert "sk-do-not-print" not in config.describe()


class TestProviders:
    def test_deepseek_defaults(self, make_config, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
        config = make_config({"llm": {"provider": "deepseek"}})
        assert config.effective_base_url() == "https://api.deepseek.com"
        assert config.api_key() == "sk-deepseek"

    def test_qwen_defaults(self, make_config, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        config = make_config({"llm": {"provider": "qwen"}})
        assert config.effective_base_url().startswith("https://dashscope.aliyuncs.com")
        assert config.api_key() == "sk-dashscope"

    def test_explicit_base_url_wins(self, make_config, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
        config = make_config(
            {"llm": {"provider": "deepseek", "base_url": "https://proxy.internal/v1"}}
        )
        assert config.effective_base_url() == "https://proxy.internal/v1"

    def test_missing_key_names_the_provider_variable(self, make_config, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        config = make_config({"llm": {"provider": "deepseek"}})
        with pytest.raises(ConfigError) as excinfo:
            config.api_key()
        assert "DEEPSEEK_API_KEY" in str(excinfo.value)
        assert "deepseek" in str(excinfo.value)

    def test_mock_needs_no_key(self, make_config):
        assert make_config({"llm": {"provider": "mock"}}).api_key() == ""

    def test_unknown_provider_lists_the_supported_ones(self, make_config):
        with pytest.raises(ConfigError) as excinfo:
            make_config({"llm": {"provider": "anthropic"}})
        message = str(excinfo.value)
        assert "deepseek" in message
        assert "qwen" in message


class TestPromptFormat:
    def test_text_format_is_accepted(self, make_config):
        assert make_config({"prompts": {"format": "text"}}).get("prompts.format") == "text"

    def test_unknown_format_is_rejected(self, make_config):
        with pytest.raises(ConfigError) as excinfo:
            make_config({"prompts": {"format": "yaml"}})
        assert "prompts.format" in str(excinfo.value)

    def test_default_format_is_json(self, make_config):
        assert make_config().get("prompts.format") == "json"

    def test_model_params_must_be_a_mapping(self, make_config):
        with pytest.raises(ConfigError) as excinfo:
            make_config({"llm": {"model_params": ["not", "a", "map"]}})
        assert "model_params" in str(excinfo.value)
