"""Tests for provider registry, factory, and LiteLLM-backed adapters."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osoji.config import Config
from osoji.llm.anthropic import AnthropicProvider
from osoji.llm.factory import create_provider
from osoji.llm.google import GoogleProvider
from osoji.llm.logging import LoggingProvider
from osoji.llm.openai import OpenAIProvider
from osoji.llm.openrouter import OpenRouterProvider
from osoji.llm.rate_limited import RateLimitedProvider
from osoji.llm.registry import (
    get_provider_spec,
    normalize_provider_name,
    provider_names,
    qualify_model_name,
    strip_provider_prefix,
)
from osoji.llm.runtime import create_runtime
from osoji.llm.types import (
    CompletionResult,
    CompletionOptions,
    Message,
    MessageRole,
    RequiredToolCallError,
    ToolDefinition,
)

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    },
    "required": ["value"],
}

TOOL_DEF = ToolDefinition(
    name="test_tool",
    description="A test tool",
    input_schema=SIMPLE_SCHEMA,
)


def _make_openai_response(*, content=None, tool_calls=None, input_tokens=100, output_tokens=50, finish_reason="tool_calls"):
    message = {}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
        "model": "gpt-test",
    }


def test_provider_names_include_all_supported_providers():
    assert provider_names() == ("anthropic", "google", "openai", "openrouter")


def test_registry_normalizes_and_reports_metadata():
    assert normalize_provider_name("OPENROUTER") == "openrouter"
    google = get_provider_spec("google")
    assert google.litellm_prefix == "gemini"
    assert google.api_key_env == "GEMINI_API_KEY"


def test_model_qualification_helpers_handle_cross_provider_prefixes():
    assert qualify_model_name("openai", "gpt-4.1-mini") == "openai/gpt-4.1-mini"
    assert qualify_model_name("openrouter", "openai/gpt-4.1-mini") == "openai/gpt-4.1-mini"
    assert strip_provider_prefix("google", "gemini/gemini-2.0-flash") == "gemini-2.0-flash"


@pytest.mark.parametrize(
    ("provider_name", "env_var", "provider_type"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", AnthropicProvider),
        ("openai", "OPENAI_API_KEY", OpenAIProvider),
        ("google", "GEMINI_API_KEY", GoogleProvider),
        ("openrouter", "OPENROUTER_API_KEY", OpenRouterProvider),
    ],
)
def test_create_provider_returns_expected_wrapper(monkeypatch, provider_name, env_var, provider_type):
    monkeypatch.setenv(env_var, "test-key")

    provider = create_provider(provider_name)

    assert isinstance(provider, provider_type)


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider("bogus")


def test_create_runtime_wraps_provider_with_reservation_limiter(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = Config(root_path=tmp_path, provider="openai", model="gpt-4.1-mini")

    logging_provider, rate_limiter = create_runtime(config)
    try:
        assert isinstance(logging_provider, LoggingProvider)
        assert isinstance(logging_provider._provider, RateLimitedProvider)
        assert logging_provider.name == "openai"
        assert logging_provider._provider._rate_limiter is rate_limiter
        assert logging_provider._provider._provider._interaction_log_path == config.llm_interactions_log_path
    finally:
        asyncio.run(logging_provider.close())


def test_logging_provider_reports_length_stops_in_summary(capsys):
    class StubProvider:
        @property
        def name(self):
            return "openai"

        async def complete(self, messages, system, options):
            return CompletionResult(
                content=None,
                tool_calls=[],
                input_tokens=100,
                output_tokens=32,
                model="gpt-test",
                stop_reason="length",
            )

        async def close(self):
            return None

    provider = LoggingProvider(StubProvider(), verbose=True)

    asyncio.run(
        provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Return plain text.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                max_tokens=128,
                reservation_key="shadow.file",
            ),
        )
    )

    stdout = capsys.readouterr().out
    assert "[warn] stop_reason=length" in stdout

    summary = provider.get_token_summary()
    assert "Warnings: 1 response(s) ended with stop_reason=length" in summary
    assert "shadow.file (model=gpt-test, max_tokens=128)" in summary


@pytest.fixture
def openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return OpenAIProvider()


def test_openai_provider_retries_invalid_tool_input(openai_provider):
    first_response = _make_openai_response(
        content=[{"type": "text", "text": "retry me"}],
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"value": "bad"}'},
            }
        ],
    )
    second_response = _make_openai_response(
        content=[{"type": "output_text", "text": "fixed"}],
        tool_calls=[
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"value": {"x": "ok"}}'},
            }
        ],
        input_tokens=120,
        output_tokens=60,
    )
    openai_provider._client.messages.create = AsyncMock(side_effect=[first_response, second_response])

    result = asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Use the tool.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "test_tool"},
            ),
        )
    )

    assert openai_provider._client.messages.create.call_count == 2
    first_call = openai_provider._client.messages.create.call_args_list[0]
    assert first_call.kwargs["model"] == "openai/gpt-4.1-mini"
    assert first_call.kwargs["tool_choice"] == {"type": "function", "function": {"name": "test_tool"}}

    retry_messages = openai_provider._client.messages.create.call_args_list[1].kwargs["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert retry_messages[-1]["role"] == "tool"
    assert retry_messages[-1]["tool_call_id"] == "call_1"
    assert "expected object" in retry_messages[-1]["content"]

    assert result.content == "fixed"
    assert result.tool_calls[0].input == {"value": {"x": "ok"}}
    assert result.input_tokens == 220
    assert result.output_tokens == 110


def test_openai_provider_retries_missing_required_tool_call(openai_provider):
    first_response = _make_openai_response(
        content=None,
        tool_calls=None,
        finish_reason="length",
    )
    second_response = _make_openai_response(
        tool_calls=[
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"value": {"x": "ok"}}'},
            }
        ],
        input_tokens=120,
        output_tokens=60,
    )
    openai_provider._client.messages.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    result = asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Use the tool.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                max_tokens=128,
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "test_tool"},
            ),
        )
    )

    assert openai_provider._client.messages.create.call_count == 2
    assert openai_provider._client.messages.create.call_args_list[1].kwargs["max_tokens"] == 256
    retry_messages = openai_provider._client.messages.create.call_args_list[1].kwargs["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "did not call the required tool `test_tool`" in retry_messages[-1]["content"]
    assert "output token limit" in retry_messages[-1]["content"]
    assert result.tool_calls[0].name == "test_tool"
    assert result.input_tokens == 220
    assert result.output_tokens == 110


def test_openai_provider_missing_required_tool_call_raises_after_three_attempts(openai_provider):
    no_tool_response = _make_openai_response(
        content=None,
        tool_calls=None,
        finish_reason="length",
    )
    openai_provider._client.messages.create = AsyncMock(
        side_effect=[no_tool_response, no_tool_response, no_tool_response]
    )

    with pytest.raises(
        RequiredToolCallError,
        match="Required tool call 'test_tool' missing after 3 attempts",
    ):
        asyncio.run(
            openai_provider.complete(
                messages=[Message(role=MessageRole.USER, content="Test")],
                system="Use the tool.",
                options=CompletionOptions(
                    model="gpt-4.1-mini",
                    max_tokens=128,
                    tools=[TOOL_DEF],
                    tool_choice={"type": "tool", "name": "test_tool"},
                ),
            )
        )

    assert openai_provider._client.messages.create.call_count == 3
    assert openai_provider._client.messages.create.call_args_list[1].kwargs["max_tokens"] == 256
    assert openai_provider._client.messages.create.call_args_list[2].kwargs["max_tokens"] == 256


def test_openai_provider_does_not_expand_retry_budget_without_length_stop(openai_provider):
    first_response = _make_openai_response(
        content="I forgot the tool",
        tool_calls=None,
        finish_reason="stop",
    )
    second_response = _make_openai_response(
        tool_calls=[
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"value": {"x": "ok"}}'},
            }
        ],
        input_tokens=120,
        output_tokens=60,
    )
    openai_provider._client.messages.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Use the tool.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                max_tokens=128,
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "test_tool"},
            ),
        )
    )

    assert openai_provider._client.messages.create.call_count == 2
    assert openai_provider._client.messages.create.call_args_list[1].kwargs["max_tokens"] == 128


def test_openai_provider_logs_each_attempt(tmp_path, openai_provider):
    log_path = tmp_path / ".osoji" / "logs" / "llm-interactions.jsonl"
    openai_provider.set_interaction_log_path(log_path)

    first_response = _make_openai_response(
        content=None,
        tool_calls=None,
        finish_reason="length",
    )
    second_response = _make_openai_response(
        tool_calls=[
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"value": {"x": "ok"}}'},
            }
        ],
        input_tokens=120,
        output_tokens=60,
    )
    openai_provider._client.messages.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Use the tool.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "test_tool"},
            ),
        )
    )

    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(entries) == 2
    assert entries[0]["attempt"] == 1
    assert entries[0]["response"]["stop_reason"] == "length"
    assert entries[0]["response"]["tool_calls"] == []
    assert entries[1]["attempt"] == 2
    assert entries[1]["response"]["tool_calls"][0]["name"] == "test_tool"


def test_openai_provider_forwards_explicit_temperature(openai_provider):
    response = _make_openai_response(content="ok", finish_reason="stop")
    openai_provider._client.messages.create = AsyncMock(return_value=response)

    result = asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Return plain text.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                temperature=0.3,
                max_tokens=32,
            ),
        )
    )

    assert openai_provider._client.messages.create.call_args.kwargs["temperature"] == 0.3
    assert result.content == "ok"


def test_default_options_omit_temperature(openai_provider):
    """CompletionOptions.temperature defaults to None, which must cause the
    provider to omit the temperature key entirely.  This is a regression guard:
    sending temperature=0.0 breaks models that reject explicit zero (e.g. gpt-5)
    and is unnecessary for structured tool-use outputs where the JSON schema
    already constrains the response.
    """
    response = _make_openai_response(content="ok", finish_reason="stop")
    openai_provider._client.messages.create = AsyncMock(return_value=response)

    result = asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Return plain text.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                max_tokens=32,
            ),
        )
    )

    kwargs = openai_provider._client.messages.create.call_args.kwargs
    assert "temperature" not in kwargs
    assert result.content == "ok"


def test_close_flushes_litellm_logging_worker(openai_provider):
    """close() drains litellm's GLOBAL_LOGGING_WORKER to prevent RuntimeWarning."""
    mock_worker = MagicMock()
    mock_worker.flush = AsyncMock()

    with patch.dict(
        "sys.modules",
        {"litellm.litellm_core_utils.logging_worker": MagicMock(GLOBAL_LOGGING_WORKER=mock_worker)},
    ):
        asyncio.run(openai_provider.close())

    mock_worker.flush.assert_awaited_once()


def test_close_swallows_logging_worker_errors(openai_provider):
    """close() must not raise if litellm internals change or fail."""
    with patch.dict(
        "sys.modules",
        {"litellm.litellm_core_utils.logging_worker": None},
    ):
        # Should not raise — the ImportError is swallowed
        asyncio.run(openai_provider.close())


def test_litellm_suppress_debug_info():
    """Importing litellm_provider sets suppress_debug_info to suppress noisy prints."""
    import litellm

    # Module-level side effect: importing the provider module sets this flag
    import osoji.llm.litellm_provider  # noqa: F401

    assert litellm.suppress_debug_info is True
