"""Tests for provider registry, factory, and LiteLLM-backed adapters."""

import asyncio
from unittest.mock import AsyncMock

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
from osoji.llm.types import CompletionOptions, Message, MessageRole, ToolDefinition

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
    finally:
        asyncio.run(logging_provider.close())


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


def test_openai_provider_forwards_zero_temperature(openai_provider):
    response = _make_openai_response(content="ok", finish_reason="stop")
    openai_provider._client.messages.create = AsyncMock(return_value=response)

    result = asyncio.run(
        openai_provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Return plain text.",
            options=CompletionOptions(
                model="gpt-4.1-mini",
                temperature=0.0,
                max_tokens=32,
            ),
        )
    )

    assert openai_provider._client.messages.create.call_args.kwargs["temperature"] == 0.0
    assert result.content == "ok"
