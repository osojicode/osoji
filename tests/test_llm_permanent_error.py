"""Tests for permanent-provider-error classification and the circuit breaker.

Billing/credit exhaustion and auth failures are not transient: every retry
fails identically. ``classify_permanent_error`` turns the raw SDK error into a
typed :class:`ProviderPermanentError`, and ``RateLimitedProvider`` trips a
shared :class:`ProviderCircuitBreaker` on the first one so the remaining LLM
work short-circuits instead of burning wall-clock (osoji issue #160).
"""

from __future__ import annotations

import asyncio
from collections import deque

import pytest

from osoji.llm.base import LLMProvider
from osoji.llm.errors import ProviderCircuitBreaker, classify_permanent_error
from osoji.llm.rate_limited import RateLimitedProvider
from osoji.llm.types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    ProviderPermanentError,
)
from osoji.rate_limiter import RateLimiter, RateLimiterConfig


# --- test doubles for SDK errors ----------------------------------------------


class _FakeStatusError(Exception):
    """Stand-in for an SDK APIStatusError: carries status_code + message/body."""

    def __init__(self, message: str, *, status_code: int, body: dict | None = None,
                 code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body
        self.code = code


def _billing_400() -> _FakeStatusError:
    return _FakeStatusError(
        "Error code: 400 - Your credit balance is too low to access the "
        "Anthropic API. You can go to Plans & Billing to upgrade or purchase credits.",
        status_code=400,
    )


def _malformed_400() -> _FakeStatusError:
    return _FakeStatusError(
        "Error code: 400 - messages: at least one message is required",
        status_code=400,
    )


# --- classification ------------------------------------------------------------


def test_billing_400_is_classified_permanent():
    result = classify_permanent_error(_billing_400())
    assert isinstance(result, ProviderPermanentError)
    assert result.reason == "billing"
    assert result.status_code == 400


def test_ordinary_malformed_400_is_not_permanent():
    assert classify_permanent_error(_malformed_400()) is None


def test_auth_401_is_classified_permanent():
    result = classify_permanent_error(
        _FakeStatusError("invalid x-api-key", status_code=401)
    )
    assert isinstance(result, ProviderPermanentError)
    assert result.reason == "auth"


def test_permission_403_is_classified_permanent():
    result = classify_permanent_error(
        _FakeStatusError("permission denied", status_code=403)
    )
    assert isinstance(result, ProviderPermanentError)
    assert result.reason == "auth"


def test_openai_insufficient_quota_code_is_billing():
    exc = _FakeStatusError(
        "You exceeded your current quota, please check your plan and billing details.",
        status_code=429,
        code="insufficient_quota",
    )
    result = classify_permanent_error(exc)
    assert isinstance(result, ProviderPermanentError)
    assert result.reason == "billing"


def test_transient_500_is_not_permanent():
    assert classify_permanent_error(
        _FakeStatusError("internal server error", status_code=500)
    ) is None


def test_generic_runtime_error_is_not_permanent():
    assert classify_permanent_error(RuntimeError("boom")) is None


def test_already_typed_error_passes_through():
    original = ProviderPermanentError("dead", reason="billing")
    assert classify_permanent_error(original) is original


def test_billing_marker_on_5xx_stays_transient():
    # A stray marker on a server error must not be latched as permanent.
    exc = _FakeStatusError("credit balance service unavailable", status_code=503)
    assert classify_permanent_error(exc) is None


# --- circuit breaker -----------------------------------------------------------


def test_circuit_breaker_latches_first_error():
    breaker = ProviderCircuitBreaker()
    assert not breaker.tripped
    first = ProviderPermanentError("first", reason="billing")
    breaker.trip(first)
    assert breaker.tripped
    assert breaker.error is first
    # idempotent: a later trip does not overwrite the first-seen cause.
    breaker.trip(ProviderPermanentError("second", reason="auth"))
    assert breaker.error is first


# --- RateLimitedProvider integration ------------------------------------------


class _SequenceProvider(LLMProvider):
    def __init__(self, responses):
        self._responses = deque(responses)
        self.calls = 0

    @property
    def name(self) -> str:
        return "anthropic"

    async def complete(self, messages, system, options):
        self.calls += 1
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        pass


def _limiter() -> RateLimiter:
    return RateLimiter(RateLimiterConfig(
        requests_per_minute=600000,
        input_tokens_per_minute=1_000_000,
        output_tokens_per_minute=1_000_000,
        name="test",
    ))


def _ok() -> CompletionResult:
    return CompletionResult(
        content="ok", tool_calls=[], input_tokens=10, output_tokens=5,
        model="test", stop_reason="end_turn",
    )


def _options() -> CompletionOptions:
    return CompletionOptions(model="test-model", max_tokens=64, reservation_key="k")


def test_provider_raises_typed_error_and_trips_breaker():
    breaker = ProviderCircuitBreaker()
    provider = _SequenceProvider([_billing_400(), _ok()])
    wrapped = RateLimitedProvider(provider, _limiter(), circuit_breaker=breaker)

    async def run():
        with pytest.raises(ProviderPermanentError) as exc_info:
            await wrapped.complete(
                [Message(role=MessageRole.USER, content="hi")], None, _options(),
            )
        assert exc_info.value.reason == "billing"
        # Second call short-circuits: the underlying provider is NOT called
        # again after the breaker trips.
        with pytest.raises(ProviderPermanentError):
            await wrapped.complete(
                [Message(role=MessageRole.USER, content="hi")], None, _options(),
            )

    asyncio.run(run())
    assert breaker.tripped
    assert provider.calls == 1  # one real call, then short-circuit


def test_malformed_400_is_not_latched():
    breaker = ProviderCircuitBreaker()
    provider = _SequenceProvider([_malformed_400(), _ok()])
    wrapped = RateLimitedProvider(provider, _limiter(), circuit_breaker=breaker)

    async def run():
        # Ordinary 400 keeps its original type and does NOT trip the breaker.
        with pytest.raises(_FakeStatusError):
            await wrapped.complete(
                [Message(role=MessageRole.USER, content="hi")], None, _options(),
            )
        # A later call still goes through to the provider (no circuit open).
        result = await wrapped.complete(
            [Message(role=MessageRole.USER, content="hi")], None, _options(),
        )
        assert result.content == "ok"

    asyncio.run(run())
    assert not breaker.tripped
    assert provider.calls == 2
