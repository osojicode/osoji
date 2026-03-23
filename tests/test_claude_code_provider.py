"""Tests for the Claude Code CLI provider."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osoji.llm.claude_code import ClaudeCodeCLIError, ClaudeCodeProvider
from osoji.llm.types import (
    CompletionOptions,
    Message,
    MessageRole,
    RequiredToolCallError,
    ToolCall,
    ToolDefinition,
    ToolSchemaValidationError,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "score": {"type": "integer"},
    },
    "required": ["summary", "score"],
}

TOOL_DEF = ToolDefinition(
    name="submit_result",
    description="Submit the analysis result",
    input_schema=SIMPLE_SCHEMA,
)


def _cli_response(
    *,
    result="ok",
    structured_output=None,
    input_tokens=100,
    output_tokens=50,
    model="claude-sonnet-4-6-20250514",
    is_error=False,
):
    return {
        "type": "result",
        "subtype": "error" if is_error else "success",
        "is_error": is_error,
        "result": result,
        "structured_output": structured_output,
        "total_cost_usd": 0.01,
        "modelUsage": {
            model: {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
            }
        },
    }


def _make_process(stdout_data, *, returncode=0, stderr_data=b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout_data, stderr_data))
    proc.kill = MagicMock()
    return proc


def _provider():
    with patch("shutil.which", return_value="/usr/bin/claude"):
        return ClaudeCodeProvider()


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_provider_name():
    p = _provider()
    assert p.name == "claude-code"


def test_provider_raises_when_cli_not_found():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
            ClaudeCodeProvider()


def test_provider_uses_env_path():
    with patch.dict("os.environ", {"OSOJI_CLAUDE_PATH": "/custom/claude"}):
        with patch("shutil.which") as mock_which:
            p = ClaudeCodeProvider()
            assert p._claude_path == "/custom/claude"
            mock_which.assert_not_called()


# ------------------------------------------------------------------
# Basic text completion (no tools)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_text_completion():
    p = _provider()
    response = _cli_response(result="Hello world")
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Say hello")],
            system=None,
            options=CompletionOptions(model="claude-sonnet-4-6"),
        )

    assert result.content == "Hello world"
    assert result.tool_calls == []
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.model == "claude-sonnet-4-6-20250514"
    assert result.stop_reason == "end_turn"


# ------------------------------------------------------------------
# Forced tool → structured output
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forced_tool_structured_output():
    p = _provider()
    output = {"summary": "looks good", "score": 42}
    response = _cli_response(structured_output=output)
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Analyze this")],
            system="You are an analyzer",
            options=CompletionOptions(
                model="claude-sonnet-4-6",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "submit_result"},
            ),
        )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "submit_result"
    assert result.tool_calls[0].input == output
    assert result.tool_calls[0].id.startswith("cc_")
    assert result.content is None

    # Verify --json-schema was passed
    call_args = mock_exec.call_args[0]
    assert "--json-schema" in call_args
    schema_idx = list(call_args).index("--json-schema")
    assert json.loads(call_args[schema_idx + 1]) == SIMPLE_SCHEMA

    # Verify --system-prompt was passed
    assert "--system-prompt" in call_args


# ------------------------------------------------------------------
# Tool description injected into prompt
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_description_in_prompt():
    p = _provider()
    output = {"summary": "ok", "score": 1}
    response = _cli_response(structured_output=output)
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await p.complete(
            [Message(role=MessageRole.USER, content="Analyze")],
            system=None,
            options=CompletionOptions(
                model="sonnet",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "submit_result"},
            ),
        )

    # The prompt (piped via stdin) should contain the tool description
    comm_kwargs = proc.communicate.call_args
    stdin_data = comm_kwargs[1].get("input", b"") or (comm_kwargs[0][0] if comm_kwargs[0] else b"")
    prompt = stdin_data.decode("utf-8")
    assert "submit_result" in prompt
    assert "Submit the analysis result" in prompt


# ------------------------------------------------------------------
# Validation retry
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_retry_then_success():
    p = _provider()
    # First call: invalid (score is string, not integer)
    bad_output = {"summary": "ok", "score": "not-a-number"}
    # Second call: valid
    good_output = {"summary": "ok", "score": 5}

    proc1 = _make_process(json.dumps(_cli_response(structured_output=bad_output)).encode())
    proc2 = _make_process(json.dumps(_cli_response(structured_output=good_output)).encode())

    with patch("asyncio.create_subprocess_exec", side_effect=[proc1, proc2]):
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Analyze")],
            system=None,
            options=CompletionOptions(
                model="sonnet",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "submit_result"},
            ),
        )

    assert result.tool_calls[0].input == good_output
    # Token counts accumulated across retries
    assert result.input_tokens == 200
    assert result.output_tokens == 100


# ------------------------------------------------------------------
# Missing structured output → retry → RequiredToolCallError
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_structured_output_raises_after_max_retries():
    p = _provider()
    # All 3 calls return no structured_output
    no_tool = _cli_response(result="I don't know")
    procs = [
        _make_process(json.dumps(no_tool).encode())
        for _ in range(3)
    ]

    with patch("asyncio.create_subprocess_exec", side_effect=procs):
        with pytest.raises(RequiredToolCallError, match="submit_result"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Analyze")],
                system=None,
                options=CompletionOptions(
                    model="sonnet",
                    tools=[TOOL_DEF],
                    tool_choice={"type": "tool", "name": "submit_result"},
                ),
            )


# ------------------------------------------------------------------
# Validation exhaustion → ToolSchemaValidationError
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_exhaustion_raises():
    p = _provider()
    bad = {"summary": "ok", "score": "nope"}
    procs = [
        _make_process(json.dumps(_cli_response(structured_output=bad)).encode())
        for _ in range(3)
    ]

    with patch("asyncio.create_subprocess_exec", side_effect=procs):
        with pytest.raises(ToolSchemaValidationError):
            await p.complete(
                [Message(role=MessageRole.USER, content="Analyze")],
                system=None,
                options=CompletionOptions(
                    model="sonnet",
                    tools=[TOOL_DEF],
                    tool_choice={"type": "tool", "name": "submit_result"},
                ),
            )


# ------------------------------------------------------------------
# Message serialization
# ------------------------------------------------------------------


def test_serialize_single_user_message():
    p = _provider()
    result = p._serialize_messages(
        [Message(role=MessageRole.USER, content="Hello")]
    )
    assert result == "Hello"


def test_serialize_multi_turn():
    p = _provider()
    result = p._serialize_messages([
        Message(role=MessageRole.USER, content="First"),
        Message(role=MessageRole.ASSISTANT, content="Response"),
        Message(role=MessageRole.USER, content="Second"),
    ])
    assert "[User]" in result
    assert "[Assistant]" in result
    assert "First" in result
    assert "Response" in result
    assert "Second" in result


def test_serialize_list_content():
    p = _provider()
    result = p._serialize_messages([
        Message(
            role=MessageRole.USER,
            content=[
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
        ),
    ])
    assert "Part 1" in result
    assert "Part 2" in result


# ------------------------------------------------------------------
# Model mapping
# ------------------------------------------------------------------


def test_model_mapping_strips_prefix():
    assert ClaudeCodeProvider._map_model("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert ClaudeCodeProvider._map_model("claude-code/sonnet") == "sonnet"


def test_model_mapping_passthrough():
    assert ClaudeCodeProvider._map_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert ClaudeCodeProvider._map_model("sonnet") == "sonnet"


# ------------------------------------------------------------------
# CLI error handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_error_raises_exception():
    p = _provider()
    proc = _make_process(b"", returncode=1, stderr_data=b"auth failed")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(ClaudeCodeCLIError, match="auth failed"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )


@pytest.mark.asyncio
async def test_cli_error_extracts_stdout_when_stderr_empty():
    """When CLI exits non-zero with empty stderr, extract error from stdout."""
    p = _provider()
    error_response = json.dumps(
        {"result": "Rate limit exceeded", "is_error": True}
    ).encode()
    proc = _make_process(error_response, returncode=1, stderr_data=b"")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(ClaudeCodeCLIError, match="Rate limit exceeded"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )


@pytest.mark.asyncio
async def test_cli_error_extracts_raw_stdout_when_not_json():
    """When CLI exits non-zero with empty stderr and non-JSON stdout, use raw text."""
    p = _provider()
    proc = _make_process(b"some raw error text", returncode=1, stderr_data=b"")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(ClaudeCodeCLIError, match="some raw error text"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )


@pytest.mark.asyncio
async def test_is_error_response_raises():
    p = _provider()
    response = _cli_response(result="Something went wrong", is_error=True)
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(ClaudeCodeCLIError, match="Something went wrong"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )


@pytest.mark.asyncio
async def test_invalid_json_raises():
    p = _provider()
    proc = _make_process(b"not json at all")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )


# ------------------------------------------------------------------
# Environment variable filtering
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_api_key_stripped_from_subprocess_env():
    """ANTHROPIC_API_KEY must not leak to CLI subprocess (would use API credits)."""
    p = _provider()
    response = _cli_response(result="ok")
    proc = _make_process(json.dumps(response).encode())

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await p.complete(
                [Message(role=MessageRole.USER, content="Hi")],
                system=None,
                options=CompletionOptions(model="sonnet"),
            )

    env = mock_exec.call_args[1]["env"]
    assert "ANTHROPIC_API_KEY" not in env


# ------------------------------------------------------------------
# Prompts always piped via stdin
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_piped_via_stdin():
    p = _provider()
    response = _cli_response(result="ok")
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await p.complete(
            [Message(role=MessageRole.USER, content="short prompt")],
            system=None,
            options=CompletionOptions(model="sonnet"),
        )

    # Prompt is NOT in the CLI args (piped via stdin instead)
    call_args = mock_exec.call_args[0]
    assert "short prompt" not in call_args
    # stdin pipe was opened
    call_kwargs = mock_exec.call_args[1]
    assert call_kwargs.get("stdin") is not None
    # prompt was passed via communicate(input=...)
    proc.communicate.assert_awaited_once()
    comm_kwargs = proc.communicate.call_args
    stdin_data = comm_kwargs[1].get("input", b"") or (comm_kwargs[0][0] if comm_kwargs[0] else b"")
    assert b"short prompt" in stdin_data


# ------------------------------------------------------------------
# Token counting from modelUsage
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_counts_from_model_usage():
    p = _provider()
    response = _cli_response(
        result="hi",
        input_tokens=500,
        output_tokens=200,
    )
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Hi")],
            system=None,
            options=CompletionOptions(model="sonnet"),
        )

    assert result.input_tokens == 500
    assert result.output_tokens == 200


# ------------------------------------------------------------------
# No tools → no json-schema
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tools_no_json_schema():
    p = _provider()
    response = _cli_response(result="text only")
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await p.complete(
            [Message(role=MessageRole.USER, content="Hi")],
            system=None,
            options=CompletionOptions(model="sonnet"),
        )

    call_args = mock_exec.call_args[0]
    assert "--json-schema" not in call_args


# ------------------------------------------------------------------
# Custom tool_input_validators
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_validators_applied():
    p = _provider()

    def reject_low_scores(name, inputs):
        if inputs.get("score", 0) < 10:
            return ["score must be >= 10"]
        return []

    # First call: score too low → retry
    low = {"summary": "ok", "score": 5}
    high = {"summary": "ok", "score": 15}
    proc1 = _make_process(json.dumps(_cli_response(structured_output=low)).encode())
    proc2 = _make_process(json.dumps(_cli_response(structured_output=high)).encode())

    with patch("asyncio.create_subprocess_exec", side_effect=[proc1, proc2]):
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Analyze")],
            system=None,
            options=CompletionOptions(
                model="sonnet",
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "submit_result"},
                tool_input_validators=[reject_low_scores],
            ),
        )

    assert result.tool_calls[0].input["score"] == 15


# ------------------------------------------------------------------
# Close is a no-op
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_noop():
    p = _provider()
    await p.close()  # should not raise


# ------------------------------------------------------------------
# --bare is NOT used (it disables OAuth subscription auth)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_flag_not_used():
    p = _provider()
    response = _cli_response(result="ok")
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await p.complete(
            [Message(role=MessageRole.USER, content="Hi")],
            system=None,
            options=CompletionOptions(model="sonnet"),
        )

    call_args = mock_exec.call_args[0]
    assert "--bare" not in call_args
    assert "--no-session-persistence" in call_args


# ------------------------------------------------------------------
# auto tool_choice → no forced tool
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_tool_choice_no_forced_tool():
    p = _provider()
    response = _cli_response(result="I used no tools")
    proc = _make_process(json.dumps(response).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        result = await p.complete(
            [Message(role=MessageRole.USER, content="Hi")],
            system=None,
            options=CompletionOptions(
                model="sonnet",
                tools=[TOOL_DEF],
                tool_choice={"type": "auto"},
            ),
        )

    assert result.tool_calls == []
    assert result.content == "I used no tools"
    call_args = mock_exec.call_args[0]
    assert "--json-schema" not in call_args
