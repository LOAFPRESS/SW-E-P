"""Tests for the OpenAI-compatible client used by every hosted provider.

No network: the SDK object is replaced with a small fake that records the request
and returns a canned response.  The interesting behaviour is the request shape
(reasoning vs normal models, per-model overrides), the answer extraction
(``content`` then ``reasoning_content``) and the parameter-repair path.
"""

import pytest

from swep.errors import LLMCallError
from swep.llm.client import OpenAIClient

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

MESSAGES = [{"role": "user", "content": "hello"}]


class _Message:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7


class _Response:
    def __init__(self, message, model="test-model"):
        self.choices = [_Choice(message)]
        self.usage = _Usage()
        self.model = model
        self.id = "req_123"


class _FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **request):
        self.owner.requests.append(request)
        if self.owner.failures:
            error = self.owner.failures.pop(0)
            if error is not None:
                raise error
        return self.owner.response


class _FakeChat:
    def __init__(self, owner):
        self.completions = _FakeCompletions(owner)


class _FakeClient:
    def __init__(self, owner):
        self.chat = _FakeChat(owner)


@pytest.fixture
def client():
    client = OpenAIClient(api_key="sk-test-key", base_url="https://api.deepseek.com")
    client.requests = []
    client.failures = []
    client.response = _Response(_Message(content="  an answer  "))
    client._client = _FakeClient(client)
    return client


class TestConstruction:
    def test_provider_name_is_kept(self):
        client = OpenAIClient(api_key="sk-x", provider="deepseek")
        assert client.name == "deepseek"

    def test_base_url_reaches_the_sdk(self):
        client = OpenAIClient(api_key="sk-x", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert "dashscope.aliyuncs.com" in str(client._client.base_url)

    def test_missing_key_is_rejected(self):
        with pytest.raises(Exception):
            OpenAIClient(api_key="")


class TestRequestShape:
    def test_normal_model_sends_temperature_and_max_tokens(self, client):
        request = client._build_request("deepseek-chat", MESSAGES, 0, 512)
        assert request["temperature"] == 0.0
        assert request["max_tokens"] == 512
        assert "max_completion_tokens" not in request

    def test_reasoning_model_sends_max_completion_tokens(self, client):
        request = client._build_request("o3-mini", MESSAGES, 0, 512)
        assert request["max_completion_tokens"] == 512
        assert "temperature" not in request

    def test_reasoning_effort_marks_a_model_as_reasoning(self):
        client = OpenAIClient(
            api_key="sk-x",
            model_params={"o4-mini": {"reasoning_effort": "medium"}},
        )
        request = client._build_request("o4-mini", MESSAGES, 0, 256)
        assert request["reasoning_effort"] == "medium"
        assert "temperature" not in request

    def test_model_params_override_defaults(self):
        client = OpenAIClient(
            api_key="sk-x",
            model_params={"qwen-max": {"temperature": 0.2, "top_p": 0.9}},
        )
        request = client._build_request("qwen-max", MESSAGES, 0, 256)
        assert request["temperature"] == 0.2
        assert request["top_p"] == 0.9

    def test_thinking_mode_drops_temperature_but_keeps_max_tokens(self):
        """DeepSeek 2026-11: thinking ignores temperature and has no max_completion_tokens."""
        client = OpenAIClient(
            api_key="sk-x",
            model_params={"deepseek-flash": {"extra_body": {"thinking": {"type": "enabled"}}}},
        )
        request = client._build_request("deepseek-flash", MESSAGES, 0, 4000)
        assert "temperature" not in request
        assert request["max_tokens"] == 4000
        assert request["extra_body"] == {"thinking": {"type": "enabled"}}

    def test_reasoning_effort_none_keeps_temperature(self):
        client = OpenAIClient(
            api_key="sk-x",
            model_params={"deepseek-flash": {"reasoning_effort": "none"}},
        )
        request = client._build_request("deepseek-flash", MESSAGES, 0, 512)
        assert request["temperature"] == 0.0
        assert request["max_tokens"] == 512
        assert request["reasoning_effort"] == "none"

    def test_reasoning_effort_high_disables_temperature(self):
        client = OpenAIClient(
            api_key="sk-x",
            model_params={"deepseek-flash": {"reasoning_effort": "high"}},
        )
        request = client._build_request("deepseek-flash", MESSAGES, 0, 4000)
        assert "temperature" not in request
        assert request["max_tokens"] == 4000


class TestAnswerExtraction:
    def test_content_is_used(self, client):
        response = client.complete(MESSAGES, "deepseek-chat")
        assert response.text == "an answer"
        assert response.prompt_tokens == 11
        assert response.completion_tokens == 7
        assert response.request_id == "req_123"

    def test_reasoning_content_is_the_fallback(self, client):
        client.response = _Response(_Message(content="", reasoning_content="from reasoning"))
        assert client.complete(MESSAGES, "deepseek-reasoner").text == "from reasoning"

    def test_empty_answer_is_a_retryable_failure(self, client):
        client.response = _Response(_Message(content="   "), model="deepseek-reasoner")
        with pytest.raises(LLMCallError) as excinfo:
            client.complete(MESSAGES, "deepseek-reasoner")
        assert excinfo.value.retryable is True
        assert "empty answer" in str(excinfo.value)


class TestParameterRepair:
    def test_temperature_rejection_is_repaired(self, client):
        client.failures = [RuntimeError("Unsupported parameter: 'temperature' is not supported")]
        client.complete(MESSAGES, "deepseek-reasoner")
        assert "temperature" in client.requests[0]
        assert "temperature" not in client.requests[1]

    def test_max_tokens_is_swapped_for_max_completion_tokens(self, client):
        client.failures = [
            RuntimeError("Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.")
        ]
        client.complete(MESSAGES, "deepseek-chat")
        assert client.requests[1]["max_completion_tokens"] == 1024
        assert "max_tokens" not in client.requests[1]

    def test_unrelated_error_is_not_repaired(self, client):
        client.failures = [RuntimeError("socket closed")]
        with pytest.raises(LLMCallError):
            client.complete(MESSAGES, "deepseek-chat")
        assert len(client.requests) == 1


class TestRedaction:
    def test_api_key_is_stripped_from_error_text(self, client):
        client.failures = [RuntimeError("bad key sk-test-key rejected")]
        with pytest.raises(LLMCallError) as excinfo:
            client.complete(MESSAGES, "deepseek-chat")
        assert "sk-test-key" not in str(excinfo.value)
        assert "***" in str(excinfo.value)
