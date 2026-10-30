from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.exceptions import (
    ModelConfigurationError,
    ModelInvocationError,
    ModelResponseError,
)
from src.models.openai_compatible import OpenAICompatibleModel


class FakeCompletions:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    completions = FakeCompletions(response=response, error=error)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def response_with_message(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_missing_model_configuration_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(ModelConfigurationError):
        OpenAICompatibleModel(client=object())


def test_parses_tool_calls_and_passes_tool_definitions() -> None:
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="get_material",
            arguments='{"material_id":"M01"}',
        ),
    )
    client, completions = fake_client(
        response_with_message(SimpleNamespace(tool_calls=[tool_call], content=None))
    )
    model = OpenAICompatibleModel(model="test-model", client=client)

    decision = model.decide(
        [{"role": "user", "content": "{}"}],
        [{"type": "function", "function": {"name": "get_material"}}],
    )

    assert decision.tool_calls[0].name == "get_material"
    assert decision.tool_calls[0].arguments == {"material_id": "M01"}
    assert completions.last_kwargs["tool_choice"] == "auto"


def test_parses_multiple_tool_calls() -> None:
    calls = [
        SimpleNamespace(
            id=f"call-{index}",
            function=SimpleNamespace(name=name, arguments="{}"),
        )
        for index, name in enumerate(["get_material", "query_slot"], start=1)
    ]
    client, _ = fake_client(
        response_with_message(SimpleNamespace(tool_calls=calls, content=None))
    )

    decision = OpenAICompatibleModel(model="test", client=client).decide([], [])

    assert [call.name for call in decision.tool_calls] == [
        "get_material",
        "query_slot",
    ]


def test_deepseek_uses_non_thinking_mode_for_tool_call_compatibility() -> None:
    client, completions = fake_client(
        response_with_message(
            SimpleNamespace(tool_calls=[], content='{"task_status":"completed"}')
        )
    )
    model = OpenAICompatibleModel(
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        client=client,
    )

    model.decide([], [])

    assert completions.last_kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert completions.last_kwargs["response_format"] == {"type": "json_object"}


def test_non_deepseek_provider_does_not_receive_deepseek_options() -> None:
    client, completions = fake_client(
        response_with_message(
            SimpleNamespace(tool_calls=[], content='{"task_status":"completed"}')
        )
    )
    model = OpenAICompatibleModel(
        model="test",
        base_url="https://example.com/v1",
        client=client,
    )

    model.decide([], [])

    assert "extra_body" not in completions.last_kwargs
    assert "response_format" not in completions.last_kwargs


def test_parses_json_from_markdown_code_fence() -> None:
    client, _ = fake_client(
        response_with_message(
            SimpleNamespace(
                tool_calls=[],
                content='```json\n{"task_status":"completed"}\n```',
            )
        )
    )

    decision = OpenAICompatibleModel(model="test", client=client).decide([], [])

    assert decision.final_output == {"task_status": "completed"}


def test_rejects_invalid_tool_arguments_json() -> None:
    call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="get_material", arguments="not-json"),
    )
    client, _ = fake_client(
        response_with_message(SimpleNamespace(tool_calls=[call], content=None))
    )

    with pytest.raises(ModelResponseError):
        OpenAICompatibleModel(model="test", client=client).decide([], [])


def test_parses_structured_final_output() -> None:
    client, _ = fake_client(
        response_with_message(
            SimpleNamespace(
                tool_calls=[],
                content='{"task_status":"completed"}',
            )
        )
    )

    decision = OpenAICompatibleModel(model="test", client=client).decide([], [])

    assert decision.final_output == {"task_status": "completed"}


@pytest.mark.parametrize("content", [None, "", "plain text", "[]"])
def test_rejects_invalid_final_output(content) -> None:
    client, _ = fake_client(
        response_with_message(SimpleNamespace(tool_calls=[], content=content))
    )

    with pytest.raises(ModelResponseError):
        OpenAICompatibleModel(model="test", client=client).decide([], [])


def test_wraps_api_error_without_exposing_credentials() -> None:
    client, _ = fake_client(error=RuntimeError("secret-key-value"))

    with pytest.raises(ModelInvocationError) as error:
        OpenAICompatibleModel(model="test", client=client).decide([], [])

    assert "secret-key-value" not in str(error.value)


def test_api_error_exposes_only_safe_status_details() -> None:
    class SafeStatusError(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"

    client, _ = fake_client(error=SafeStatusError("secret-key-value"))

    with pytest.raises(ModelInvocationError) as error:
        OpenAICompatibleModel(model="test", client=client).decide([], [])

    assert "SafeStatusError" in str(error.value)
    assert "HTTP 429" in str(error.value)
    assert "rate_limit_exceeded" in str(error.value)
    assert "secret-key-value" not in str(error.value)


def test_empty_choices_is_rejected() -> None:
    client, _ = fake_client(SimpleNamespace(choices=[]))

    with pytest.raises(ModelResponseError):
        OpenAICompatibleModel(model="test", client=client).decide([], [])

