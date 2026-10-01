"""AnthropicProvider on models that reject forced tool choice, and opt-in thinking/effort.

Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 return a 400 on
``tool_choice: {"type": "tool"}``; a forced tool also suppresses thinking on
the 4.6 models even when thinking is requested; Haiku 4.5 rejects adaptive
thinking and the effort parameter. The provider learns each rejection from
the API's own 400 (no model table) and keeps the call site's contract: the
required tool is still enforced by the retry loop (osojicode/work#108).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from osoji.llm.anthropic import AnthropicProvider
from osoji.llm.errors import ProviderCircuitBreaker
from osoji.llm.rate_limited import RateLimitedProvider
from osoji.llm.types import (
    CompletionOptions,
    Message,
    MessageRole,
    RequiredToolCallError,
    ToolDefinition,
)
from osoji.rate_limiter import RateLimiter, RateLimiterConfig

SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
}
TOOL = ToolDefinition(name="submit", description="Submit the answer", input_schema=SCHEMA)
FORCED = {"type": "tool", "name": "submit"}


class _FakeStatusError(Exception):
    """Stand-in for an SDK APIStatusError."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(f"Error code: {status_code} - {message}")
        self.status_code = status_code
        self.message = message
        self.body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}


FORCED_REJECTED = 'tool_choice: type "tool" and "any" are not supported for this model.'
THINKING_REJECTED = "adaptive thinking is not supported on this model"
EFFORT_REJECTED = "This model does not support the effort parameter."


def _response(*, tool_input=None, blocks_before=(), stop_reason="tool_use", model="claude-opus-5-5"):
    content = list(blocks_before)
    if tool_input is not None:
        content.append({"type": "tool_use", "id": "toolu_1", "name": "submit", "input": tool_input})
    return {
        "content": content,
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "model": model,
        "stop_reason": stop_reason,
    }


def _complete(provider, *, model, max_tokens=1024, system="Use the tool.", tool_choice=FORCED):
    return asyncio.run(
        provider.complete(
            messages=[Message(role=MessageRole.USER, content="Go")],
            system=system,
            options=CompletionOptions(model=model, max_tokens=max_tokens, tools=[TOOL], tool_choice=tool_choice),
        )
    )


@pytest.fixture
def make_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OSOJI_THINKING", raising=False)
    monkeypatch.delenv("OSOJI_EFFORT", raising=False)

    def make(*, thinking=None, effort=None, responses=()):
        for name, value in (("OSOJI_THINKING", thinking), ("OSOJI_EFFORT", effort)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        provider = AnthropicProvider()
        provider._client.messages.create = AsyncMock(side_effect=list(responses))
        return provider

    return make


def _calls(provider):
    return [c.kwargs for c in provider._client.messages.create.call_args_list]


def _body(sent):
    """thinking and output_config travel in extra_body (SDK-version independent)."""
    return sent.get("extra_body") or {}


# --- no knobs, a model that accepts forced choice: nothing changes -------------


def test_default_request_is_unchanged_for_shipping_models(make_provider):
    provider = make_provider(responses=[_response(tool_input={"value": "ok"}, model="claude-sonnet-4-6")])
    built = provider._build_request_kwargs(
        [Message(role=MessageRole.USER, content="Go")], "Use the tool.",
        CompletionOptions(model="claude-sonnet-4-6", max_tokens=1024, tools=[TOOL], tool_choice=FORCED),
    )
    assert provider._wire_request_kwargs(built) is built

    _complete(provider, model="claude-sonnet-4-6")
    (sent,) = _calls(provider)
    assert sent["tool_choice"] == FORCED
    assert sent["max_tokens"] == 1024
    assert "extra_body" not in sent
    assert len(sent["system"]) == 1


# --- forced choice rejected: learn, downgrade, keep enforcing the tool --------


def test_forced_choice_rejection_is_learned_and_retried_with_auto(make_provider):
    provider = make_provider(responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(tool_input={"value": "ok"}),
        _response(tool_input={"value": "again"}),
    ])

    result = _complete(provider, model="claude-opus-5-5")
    assert result.tool_calls[0].input == {"value": "ok"}

    first, second = _calls(provider)
    assert first["tool_choice"] == FORCED
    assert second["tool_choice"] == {"type": "auto"}
    assert second["system"][0] == first["system"][0]  # cached block untouched
    assert "`submit`" in second["system"][-1]["text"]
    assert second["max_tokens"] >= 8192  # a downgraded call may think

    # Learned for the provider's lifetime: the next call goes straight to auto.
    _complete(provider, model="claude-opus-5-5")
    third = _calls(provider)[2]
    assert third["tool_choice"] == {"type": "auto"}


def test_forced_choice_rejection_never_reaches_the_circuit_breaker(make_provider):
    provider = make_provider(responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(tool_input={"value": "ok"}),
    ])
    breaker = ProviderCircuitBreaker()
    limited = RateLimitedProvider(provider, RateLimiter(RateLimiterConfig()), circuit_breaker=breaker)

    result = asyncio.run(
        limited.complete(
            messages=[Message(role=MessageRole.USER, content="Go")],
            system="Use the tool.",
            options=CompletionOptions(model="claude-opus-5-5", max_tokens=1024, tools=[TOOL], tool_choice=FORCED),
        )
    )
    assert result.tool_calls[0].input == {"value": "ok"}
    assert not breaker.tripped


def test_auto_choice_still_enforces_the_required_tool(make_provider):
    provider = make_provider(responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(blocks_before=[{"type": "text", "text": "I think the answer is ok."}], stop_reason="end_turn"),
        _response(tool_input={"value": "ok"}),
    ])

    result = _complete(provider, model="claude-opus-5-5")
    assert result.tool_calls[0].input == {"value": "ok"}
    retry = _calls(provider)[2]
    assert retry["tool_choice"] == {"type": "auto"}
    assert "did not call the required tool `submit`" in retry["messages"][-1]["content"]


def test_other_400s_still_raise(make_provider):
    provider = make_provider(responses=[_FakeStatusError("messages: at least one message is required")])
    with pytest.raises(_FakeStatusError):
        _complete(provider, model="claude-opus-5-5")
    assert len(_calls(provider)) == 1


def test_refusal_fails_fast_without_retries(make_provider):
    provider = make_provider(responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(stop_reason="refusal"),
    ])
    with pytest.raises(RequiredToolCallError) as info:
        _complete(provider, model="claude-opus-5-5")
    assert info.value.stop_reason == "refusal"
    assert len(_calls(provider)) == 2  # the learning 400, then one refused attempt


# --- opt-in thinking and effort ------------------------------------------------


def test_thinking_on_a_46_model_downgrades_the_forced_tool(make_provider):
    provider = make_provider(thinking="adaptive", effort="high", responses=[
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6",
                  blocks_before=[{"type": "thinking", "thinking": "", "signature": "sig"}]),
    ])
    _complete(provider, model="claude-sonnet-4-6", max_tokens=2048)
    (sent,) = _calls(provider)
    assert _body(sent)["thinking"] == {"type": "adaptive"}
    assert _body(sent)["output_config"] == {"effort": "high"}
    assert sent["tool_choice"] == {"type": "auto"}  # a forced tool would suppress thinking
    assert sent["max_tokens"] == 8192


def test_effort_alone_keeps_forced_choice(make_provider):
    provider = make_provider(effort="medium", responses=[
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6"),
    ])
    _complete(provider, model="claude-sonnet-4-6")
    (sent,) = _calls(provider)
    assert _body(sent)["output_config"] == {"effort": "medium"}
    assert sent["tool_choice"] == FORCED
    assert sent["max_tokens"] == 1024


def test_small_tier_learns_it_supports_neither_knob(make_provider):
    provider = make_provider(thinking="adaptive", effort="high", responses=[
        _FakeStatusError(THINKING_REJECTED),
        _FakeStatusError(EFFORT_REJECTED),
        _response(tool_input={"value": "ok"}, model="claude-haiku-4-5-20251001"),
    ])
    _complete(provider, model="claude-haiku-4-5-20251001")
    first, second, third = _calls(provider)
    assert _body(first)["thinking"] == {"type": "adaptive"} and first["tool_choice"] == {"type": "auto"}
    assert "thinking" not in _body(second) and _body(second)["output_config"] == {"effort": "high"}
    assert "extra_body" not in third
    assert third["tool_choice"] == FORCED  # no thinking, so no reason to downgrade
    assert third["max_tokens"] == 1024


def test_invalid_knob_values_fail_at_construction(make_provider):
    with pytest.raises(RuntimeError, match="OSOJI_EFFORT"):
        make_provider(effort="extreme")


# --- thinking blocks, logging, reservations ------------------------------------


def test_thinking_blocks_are_passed_back_on_a_validation_retry(make_provider):
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}
    provider = make_provider(thinking="adaptive", responses=[
        _response(tool_input={"value": 7}, model="claude-sonnet-4-6", blocks_before=[thinking]),
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6"),
    ])
    _complete(provider, model="claude-sonnet-4-6")
    retry = _calls(provider)[1]
    assistant = retry["messages"][-2]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == thinking
    assert assistant["content"][1]["type"] == "tool_use"


def test_interaction_log_records_requested_and_wire_choices(make_provider, tmp_path):
    provider = make_provider(effort="high", responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(tool_input={"value": "ok"}),
    ])
    log = tmp_path / "llm.jsonl"
    provider.set_interaction_log_path(log)
    _complete(provider, model="claude-opus-5-5")

    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2
    rejected, ok = entries
    assert "error" in rejected
    for entry in entries:
        assert entry["request"]["tool_choice"] == FORCED  # what the call site asked for
        assert entry["request"]["effort"] == "high"
    assert ok["request"]["wire_tool_choice"] == {"type": "auto"}
    assert ok["request"]["max_tokens"] >= 8192


def test_rate_limiter_reserves_the_thinking_floor(make_provider):
    provider = make_provider(thinking="adaptive")
    limited = RateLimitedProvider(provider, RateLimiter(RateLimiterConfig()))
    options = CompletionOptions(model="claude-sonnet-4-6", max_tokens=1024, tools=[TOOL], tool_choice=FORCED)
    assert limited._effective_max_tokens(options) == 8192

    plain = make_provider()
    assert RateLimitedProvider(plain, RateLimiter(RateLimiterConfig()))._effective_max_tokens(options) == 1024


# --- review fixes ---------------------------------------------------------------


def test_truncated_thinking_call_grows_its_budget(make_provider):
    """The retry arithmetic starts from the floored budget actually sent, so
    a truncated thinking response is retried with more room, not the same."""
    provider = make_provider(thinking="adaptive", responses=[
        _response(stop_reason="max_tokens", model="claude-sonnet-4-6",
                  blocks_before=[{"type": "thinking", "thinking": "", "signature": "s"}]),
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6"),
    ])
    result = _complete(provider, model="claude-sonnet-4-6", max_tokens=1024)
    first, second = _calls(provider)
    assert first["max_tokens"] == 8192
    assert second["max_tokens"] == 16384
    assert result.max_tokens_sent == 16384


def test_budget_follows_a_rejection_learned_on_the_first_attempt(make_provider):
    provider = make_provider(responses=[
        _FakeStatusError(FORCED_REJECTED),
        _response(stop_reason="max_tokens"),
        _response(tool_input={"value": "ok"}),
    ])
    _complete(provider, model="claude-opus-5-5", max_tokens=1024)
    _, second, third = _calls(provider)
    assert second["max_tokens"] == 8192
    assert third["max_tokens"] == 16384


def test_an_effort_level_the_model_lacks_falls_back_to_its_default(make_provider):
    provider = make_provider(effort="xhigh", responses=[
        _FakeStatusError("This model does not support effort level 'xhigh'. Supported levels: high, low, max, medium."),
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6"),
    ])
    _complete(provider, model="claude-sonnet-4-6")
    first, second = _calls(provider)
    assert _body(first)["output_config"] == {"effort": "xhigh"}
    assert "extra_body" not in second


def test_any_choice_is_not_downgraded_for_thinking(make_provider):
    provider = make_provider(thinking="adaptive", responses=[
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6"),
    ])
    _complete(provider, model="claude-sonnet-4-6", tool_choice={"type": "any"})
    (sent,) = _calls(provider)
    assert sent["tool_choice"] == {"type": "any"}
    assert len(sent["system"]) == 1


def test_length_stop_diagnostics_report_the_budget_sent(make_provider):
    from osoji.llm.logging import LoggingProvider

    provider = make_provider(thinking="adaptive", responses=[
        _response(tool_input={"value": "ok"}, model="claude-sonnet-4-6", stop_reason="length"),
    ])
    logged = LoggingProvider(provider)
    asyncio.run(logged.complete(
        messages=[Message(role=MessageRole.USER, content="Go")],
        system="Use the tool.",
        options=CompletionOptions(model="claude-sonnet-4-6", max_tokens=1024, tools=[TOOL], tool_choice=FORCED),
    ))
    assert "max_tokens=8192" in logged._stats.length_stop_examples[0]
