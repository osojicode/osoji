"""Tests for the tool-input validation + retry mechanism in AnthropicProvider."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from osoji.llm.types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    PromptTooLargeError,
    ToolCall,
    ToolDefinition,
    ToolSchemaValidationError,
)
from osoji.llm.anthropic import AnthropicProvider


def _make_response(content_blocks, input_tokens=100, output_tokens=50):
    """Build a fake Anthropic API response."""
    blocks = []
    for b in content_blocks:
        blocks.append(SimpleNamespace(**b))
    return SimpleNamespace(
        content=blocks,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        model="claude-test",
        stop_reason="tool_use",
    )


def _tool_use_block(tool_id, name, tool_input):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def _text_block(text):
    return {"type": "text", "text": text}


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

FORCED_CHOICE = {"type": "tool", "name": "test_tool"}


@pytest.fixture
def provider():
    """Create a provider with mocked client."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("osoji.llm.anthropic.anthropic.AsyncAnthropic"):
            p = AnthropicProvider()
    return p


class TestValidInputSkipsRetry:
    """When tool input matches schema, no retry should happen."""

    def test_valid_input_no_retry(self, provider):
        valid_input = {"value": {"x": "hello"}}
        response = _make_response(
            [_tool_use_block("tc1", "test_tool", valid_input)],
            input_tokens=100,
            output_tokens=50,
        )
        provider._client.messages.create = AsyncMock(return_value=response)

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].input == valid_input
        # API called exactly once
        assert provider._client.messages.create.call_count == 1

    def test_multiple_text_blocks_are_concatenated(self, provider):
        response = _make_response(
            [
                _text_block("hello "),
                _text_block("world"),
                _tool_use_block("tc1", "test_tool", {"value": {"x": "ok"}}),
            ],
            input_tokens=100,
            output_tokens=50,
        )
        provider._client.messages.create = AsyncMock(return_value=response)

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        assert result.content == "hello world"


class TestInvalidInputTriggersRetry:
    """When tool input has schema errors, provider should retry once."""

    def test_retry_on_schema_error(self, provider):
        # First response: value is a string instead of object
        bad_input = {"value": "not-an-object"}
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)],
            input_tokens=100,
            output_tokens=50,
        )
        # Second response: corrected
        good_input = {"value": {"x": "fixed"}}
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", good_input)],
            input_tokens=120,
            output_tokens=60,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        # Should have called API twice
        assert provider._client.messages.create.call_count == 2
        # Result from second call
        assert result.tool_calls[0].input == good_input
        # Tokens summed
        assert result.input_tokens == 220
        assert result.output_tokens == 110

    def test_retry_multiple_text_blocks_are_concatenated(self, provider):
        bad_input = {"value": "not-an-object"}
        first_response = _make_response(
            [
                _text_block("retry "),
                _tool_use_block("tc1", "test_tool", bad_input),
            ],
            input_tokens=100,
            output_tokens=50,
        )
        good_input = {"value": {"x": "fixed"}}
        second_response = _make_response(
            [
                _text_block("fixed "),
                _text_block("response"),
                _tool_use_block("tc2", "test_tool", good_input),
            ],
            input_tokens=120,
            output_tokens=60,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        assert result.content == "fixed response"

    def test_retry_message_contains_errors(self, provider):
        """Verify the retry message includes validation errors."""
        bad_input = {"value": "not-an-object"}
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)]
        )
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", {"value": {"x": "ok"}})]
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        asyncio.run(provider.complete(messages, None, options))

        # Check the retry call's messages
        retry_call = provider._client.messages.create.call_args_list[1]
        retry_messages = retry_call.kwargs["messages"]

        # Should have: original user msg + assistant (tool_use) + user (tool_result)
        assert len(retry_messages) == 3
        assert retry_messages[1]["role"] == "assistant"
        assert retry_messages[2]["role"] == "user"

        # tool_result should have is_error=True
        tool_result_block = retry_messages[2]["content"][0]
        assert tool_result_block["is_error"] is True
        assert "expected object" in tool_result_block["content"]


class TestTokenSumming:
    """Tokens from both attempts are summed in the result."""

    def test_tokens_summed(self, provider):
        bad_input = {"value": "wrong"}
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)],
            input_tokens=200,
            output_tokens=80,
        )
        good_input = {"value": {"x": "ok"}}
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", good_input)],
            input_tokens=300,
            output_tokens=90,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))
        assert result.input_tokens == 500
        assert result.output_tokens == 170


class TestNonForcedSkipsValidation:
    """Non-forced tool_choice should skip validation entirely."""

    def test_auto_tool_choice_no_retry(self, provider):
        bad_input = {"value": "not-an-object"}
        response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)]
        )
        provider._client.messages.create = AsyncMock(return_value=response)

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice={"type": "auto"},
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        # Only one call — no retry for auto tool_choice
        assert provider._client.messages.create.call_count == 1
        assert result.tool_calls[0].input == bad_input

    def test_no_tool_choice_no_retry(self, provider):
        bad_input = {"value": "not-an-object"}
        response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)]
        )
        provider._client.messages.create = AsyncMock(return_value=response)

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=None,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))
        assert provider._client.messages.create.call_count == 1


class LegacyOnlyRetriesOnce:
    """Even if the second attempt has errors, we return it as-is."""

    def test_second_bad_response_returned(self, provider):
        bad_input = {"value": "wrong"}
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", bad_input)],
            input_tokens=100,
            output_tokens=50,
        )
        # Second response is also bad
        still_bad_input = {"value": 42}
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", still_bad_input)],
            input_tokens=120,
            output_tokens=60,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        # Only two calls — no third attempt
        assert provider._client.messages.create.call_count == 2
        # Returns the second (still bad) result
        assert result.tool_calls[0].input == still_bad_input
        assert result.input_tokens == 220
        assert result.output_tokens == 110


class TestRetryExhaustion:
    """Forced tool retries should use up to three attempts, then raise."""

    def test_third_attempt_can_recover(self, provider):
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", {"value": "wrong"})],
            input_tokens=100,
            output_tokens=50,
        )
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", {"value": 42})],
            input_tokens=120,
            output_tokens=60,
        )
        good_input = {"value": {"x": "fixed-on-third"}}
        third_response = _make_response(
            [_tool_use_block("tc3", "test_tool", good_input)],
            input_tokens=140,
            output_tokens=70,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response, third_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        assert provider._client.messages.create.call_count == 3
        assert result.tool_calls[0].input == good_input
        assert result.input_tokens == 360
        assert result.output_tokens == 180

    def test_third_bad_response_raises(self, provider):
        first_response = _make_response(
            [_tool_use_block("tc1", "test_tool", {"value": "wrong"})],
            input_tokens=100,
            output_tokens=50,
        )
        second_response = _make_response(
            [_tool_use_block("tc2", "test_tool", {"value": 42})],
            input_tokens=120,
            output_tokens=60,
        )
        third_response = _make_response(
            [_tool_use_block("tc3", "test_tool", {"value": []})],
            input_tokens=140,
            output_tokens=70,
        )
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response, third_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[TOOL_DEF],
            tool_choice=FORCED_CHOICE,
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        with pytest.raises(ToolSchemaValidationError, match="Schema validation failed after 3 attempts"):
            asyncio.run(provider.complete(messages, None, options))

        assert provider._client.messages.create.call_count == 3


class TestPromptBudget:
    """Oversized requests should fail locally before hitting the provider."""

    def test_preflight_rejects_large_prompt(self, provider):
        provider._client.messages.create = AsyncMock()

        options = CompletionOptions(
            model="claude-test",
            max_input_tokens=10,
        )
        messages = [Message(role=MessageRole.USER, content="x" * 1_000)]

        with pytest.raises(PromptTooLargeError, match="Estimated prompt is too long"):
            asyncio.run(provider.complete(messages, "system prompt", options))

        provider._client.messages.create.assert_not_called()


class TestMultipleToolCalls:
    """Handle responses with multiple tool_use blocks."""

    def test_one_valid_one_invalid(self, provider):
        """Only retry if at least one tool call has errors."""
        tool_def_a = ToolDefinition(
            name="tool_a",
            description="Tool A",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        tool_def_b = ToolDefinition(
            name="tool_b",
            description="Tool B",
            input_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        )

        first_response = _make_response([
            _tool_use_block("tc1", "tool_a", {"name": "ok"}),
            _tool_use_block("tc2", "tool_b", {"count": "not-int"}),
        ])
        second_response = _make_response([
            _tool_use_block("tc3", "tool_a", {"name": "ok"}),
            _tool_use_block("tc4", "tool_b", {"count": 5}),
        ])
        provider._client.messages.create = AsyncMock(
            side_effect=[first_response, second_response]
        )

        options = CompletionOptions(
            model="claude-test",
            tools=[tool_def_a, tool_def_b],
            tool_choice={"type": "tool", "name": "tool_a"},
        )
        messages = [Message(role=MessageRole.USER, content="test")]

        result = asyncio.run(provider.complete(messages, None, options))

        # Retry happened
        assert provider._client.messages.create.call_count == 2

        # Check that the retry included OK for tool_a and error for tool_b
        retry_call = provider._client.messages.create.call_args_list[1]
        retry_messages = retry_call.kwargs["messages"]
        tool_results = retry_messages[2]["content"]
        assert len(tool_results) == 2
        # tool_a was OK
        ok_result = [tr for tr in tool_results if tr["tool_use_id"] == "tc1"][0]
        assert ok_result["content"] == "OK"
        assert "is_error" not in ok_result
        # tool_b had error
        err_result = [tr for tr in tool_results if tr["tool_use_id"] == "tc2"][0]
        assert err_result["is_error"] is True
