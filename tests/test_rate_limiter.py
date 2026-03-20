"""Tests for reservation-based rate limiting."""

from __future__ import annotations

import asyncio
import os
from collections import deque
from types import SimpleNamespace
from unittest import mock

import pytest

from osoji.llm.base import LLMProvider
from osoji.llm.rate_limited import RateLimitedProvider
from osoji.llm.types import CompletionOptions, CompletionResult, Message, MessageRole
from osoji.rate_limiter import (
    ANTHROPIC_DEFAULTS,
    GOOGLE_DEFAULTS,
    OPENAI_DEFAULTS,
    RateLimiter,
    RateLimiterConfig,
    get_config_with_overrides,
    get_default_config,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


class SequenceProvider(LLMProvider):
    def __init__(self, responses: list[CompletionResult | Exception], *, name: str = "anthropic") -> None:
        self._responses = deque(responses)
        self._name = name
        self.calls: list[tuple[list[Message], str | None, CompletionOptions]] = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        self.calls.append((messages, system, options))
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True


def _ticket_kwargs(*, key: str = "test", estimated_input: int = 0, reserved_output: int | None = None, max_output: int = 0) -> dict[str, int | str | None]:
    return {
        "reservation_key": key,
        "estimated_input_tokens": estimated_input,
        "reserved_output_tokens": reserved_output,
        "max_output_tokens": max_output,
    }


def _completion(*, input_tokens: int, output_tokens: int) -> CompletionResult:
    return CompletionResult(
        content="ok",
        tool_calls=[],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="test-model",
        stop_reason="end_turn",
    )


class TestProviderDefaults:
    def test_anthropic_defaults(self):
        assert ANTHROPIC_DEFAULTS.requests_per_minute == 4000
        assert ANTHROPIC_DEFAULTS.input_tokens_per_minute == 2_000_000
        assert ANTHROPIC_DEFAULTS.output_tokens_per_minute == 400_000
        assert ANTHROPIC_DEFAULTS.name == "anthropic"

    def test_openai_defaults(self):
        assert OPENAI_DEFAULTS.requests_per_minute == 500
        assert OPENAI_DEFAULTS.input_tokens_per_minute == 500_000
        assert OPENAI_DEFAULTS.output_tokens_per_minute == 500_000
        assert OPENAI_DEFAULTS.name == "openai"

    def test_google_defaults(self):
        assert GOOGLE_DEFAULTS.requests_per_minute == 300
        assert GOOGLE_DEFAULTS.input_tokens_per_minute == 5_000_000
        assert GOOGLE_DEFAULTS.output_tokens_per_minute == 5_000_000
        assert GOOGLE_DEFAULTS.name == "google"

    def test_get_default_config_is_copy(self):
        config = get_default_config("anthropic")
        config.requests_per_minute = 1
        assert ANTHROPIC_DEFAULTS.requests_per_minute == 4000

    def test_get_default_config_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_default_config("unknown")


class TestEnvironmentOverrides:
    def test_rpm_override(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_RPM": "120"}):
            config = get_config_with_overrides("anthropic")
        assert config.requests_per_minute == 120
        assert config.input_tokens_per_minute == 2_000_000

    def test_legacy_tpm_override_sets_both(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_TPM": "200000"}):
            config = get_config_with_overrides("anthropic")
        assert config.input_tokens_per_minute == 200_000
        assert config.output_tokens_per_minute == 200_000

    def test_specific_overrides_take_precedence(self):
        with mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_TPM": "100000",
                "ANTHROPIC_INPUT_TPM": "3000000",
                "ANTHROPIC_OUTPUT_TPM": "500000",
            },
        ):
            config = get_config_with_overrides("anthropic")
        assert config.input_tokens_per_minute == 3_000_000
        assert config.output_tokens_per_minute == 500_000


class TestRateLimiter:
    def test_acquire_reserves_budget_proactively(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=200, reserved_output=300, max_output=300))
            stats = limiter.get_stats()
            assert ticket.reserved_input_tokens == 200
            assert ticket.reserved_output_tokens == 300
            assert stats.inflight_requests == 1
            assert stats.inflight_reserved_input_tokens == 200
            assert stats.inflight_reserved_output_tokens == 300
            assert stats.input_token_allowance == pytest.approx(800.0)
            assert stats.output_token_allowance == pytest.approx(700.0)

        asyncio.run(run())

    def test_acquire_waits_when_reservations_exhaust_input_budget(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=6000,
                output_tokens_per_minute=6000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            await limiter.acquire(**_ticket_kwargs(estimated_input=6000))
            await limiter.acquire(**_ticket_kwargs(estimated_input=3000))

        asyncio.run(run())
        assert clock.sleeps == [pytest.approx(30.0)]
        stats = limiter.get_stats()
        assert stats.inflight_reserved_input_tokens == 9000
        assert stats.input_token_allowance == pytest.approx(0.0)

    def test_finalize_success_refunds_unused_slack(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=200, reserved_output=300, max_output=300))
            stats = await limiter.finalize_success(
                ticket,
                actual_input_tokens=120,
                actual_output_tokens=80,
            )
            assert stats.inflight_requests == 0
            assert stats.input_token_allowance == pytest.approx(880.0)
            assert stats.output_token_allowance == pytest.approx(920.0)
            assert limiter.get_cumulative_tokens() == (120, 80)

        asyncio.run(run())

    def test_finalize_success_tracks_under_reservation_deficits(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=100, reserved_output=100, max_output=100))
            stats = await limiter.finalize_success(
                ticket,
                actual_input_tokens=100,
                actual_output_tokens=180,
            )
            assert stats.output_token_allowance == pytest.approx(820.0)
            assert stats.under_reserved_count == 1

        asyncio.run(run())
        summary = limiter.get_summary()
        assert "Under-reserved: test=1" in summary

    def test_finalize_failure_refunds_non_rate_limit_requests(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=250, reserved_output=300, max_output=300))
            stats = await limiter.finalize_failure(ticket, is_rate_limit=False)
            assert stats.inflight_requests == 0
            assert stats.input_token_allowance == pytest.approx(1000.0)
            assert stats.output_token_allowance == pytest.approx(1000.0)

        asyncio.run(run())

    def test_finalize_failure_applies_provider_cooldown(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=100, reserved_output=200, max_output=200))
            stats = await limiter.finalize_failure(ticket, is_rate_limit=True, retry_after=5.0)
            assert stats.rate_limit_retries == 1
            assert stats.next_request_in_ms == pytest.approx(5000.0)
            next_ticket = await limiter.acquire(**_ticket_kwargs(estimated_input=0, max_output=400))
            assert next_ticket.reserved_output_tokens == 400

        asyncio.run(run())
        assert clock.sleeps == [pytest.approx(5.0)]

    def test_output_reservation_relaxes_after_warmup(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=10_000,
                output_tokens_per_minute=10_000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )

        async def run() -> None:
            for _ in range(5):
                ticket = await limiter.acquire(**_ticket_kwargs(key="shadow.file", estimated_input=50, max_output=500))
                assert ticket.reserved_output_tokens == 500
                await limiter.finalize_success(
                    ticket,
                    actual_input_tokens=50,
                    actual_output_tokens=40,
                )

            tuned = await limiter.acquire(**_ticket_kwargs(key="shadow.file", estimated_input=50, max_output=500))
            assert tuned.reserved_output_tokens == 128

        asyncio.run(run())


class RetryableError(Exception):
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        super().__init__("retry me")
        self.response = SimpleNamespace(headers=headers or {})


class TestRateLimitedProvider:
    def test_success_attaches_rate_limit_metadata(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=10_000,
                output_tokens_per_minute=10_000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        provider = SequenceProvider([_completion(input_tokens=120, output_tokens=80)])
        wrapped = RateLimitedProvider(provider, limiter)

        async def run() -> None:
            result = await wrapped.complete(
                messages=[Message(role=MessageRole.USER, content="hello world")],
                system="system prompt",
                options=CompletionOptions(
                    model="test-model",
                    max_tokens=256,
                    reservation_key="shadow.file",
                ),
            )
            assert result.rate_limit is not None
            assert result.rate_limit.reservation_key == "shadow.file"
            assert result.rate_limit.actual_input_tokens == 120
            assert result.rate_limit.actual_output_tokens == 80
            assert result.rate_limit.reserved_input_tokens > 0

        asyncio.run(run())
        assert limiter.get_cumulative_tokens() == (120, 80)

    def test_rate_limit_errors_retry_after_cooldown(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=100_000,
                output_tokens_per_minute=100_000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        provider = SequenceProvider(
            [
                RetryableError({"retry-after-ms": "2000"}),
                _completion(input_tokens=90, output_tokens=30),
            ]
        )
        wrapped = RateLimitedProvider(provider, limiter)

        async def run() -> None:
            with mock.patch.object(RateLimitedProvider, "_is_retryable_error", return_value=True):
                result = await wrapped.complete(
                    messages=[Message(role=MessageRole.USER, content="hello")],
                    system=None,
                    options=CompletionOptions(
                        model="test-model",
                        max_tokens=256,
                        reservation_key="audit.verify_debris",
                    ),
                )
            assert result.rate_limit is not None
            assert result.rate_limit.retry_count == 1

        asyncio.run(run())
        assert len(provider.calls) == 2
        assert clock.sleeps == [pytest.approx(2.0)]
        assert limiter.get_stats().rate_limit_retries == 1

    def test_non_retryable_failures_refund_reservations(self):
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(
                requests_per_minute=600000,
                input_tokens_per_minute=1000,
                output_tokens_per_minute=1000,
                name="test",
            ),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        provider = SequenceProvider([RuntimeError("boom")])
        wrapped = RateLimitedProvider(provider, limiter)

        async def run() -> None:
            with pytest.raises(RuntimeError, match="boom"):
                await wrapped.complete(
                    messages=[Message(role=MessageRole.USER, content="hello")],
                    system=None,
                    options=CompletionOptions(
                        model="test-model",
                        max_tokens=256,
                        reservation_key="shadow.file",
                    ),
                )

        asyncio.run(run())
        stats = limiter.get_stats()
        assert stats.inflight_requests == 0
        assert stats.input_token_allowance == pytest.approx(1000.0)
        assert stats.output_token_allowance == pytest.approx(1000.0)


class TestUpdateLimits:
    """Tests for dynamic rate limit auto-tuning via update_limits()."""

    def test_upward_update_changes_limits(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=20_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        changed = asyncio.run(rl.update_limits(requests_per_minute=200, input_tokens_per_minute=100_000, output_tokens_per_minute=40_000))
        assert changed is True
        assert rl._config.requests_per_minute == 200
        assert rl._config.input_tokens_per_minute == 100_000
        assert rl._config.output_tokens_per_minute == 40_000
        assert rl._request_interval_ms == pytest.approx(60_000 / 200)
        assert rl._input_token_refill_rate == pytest.approx(100_000 / 60_000)
        assert rl._output_token_refill_rate == pytest.approx(40_000 / 60_000)

    def test_downward_update_rejected(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=20_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        changed = asyncio.run(rl.update_limits(requests_per_minute=50, input_tokens_per_minute=30_000))
        assert changed is False
        assert rl._config.requests_per_minute == 100
        assert rl._config.input_tokens_per_minute == 50_000

    def test_second_call_is_noop(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=20_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        asyncio.run(rl.update_limits(requests_per_minute=200))
        assert rl._auto_tuned is True
        changed = asyncio.run(rl.update_limits(requests_per_minute=500))
        assert changed is False
        assert rl._config.requests_per_minute == 200

    def test_mixed_update_partial(self) -> None:
        """One limit goes up, one stays — should report changed."""
        clock = FakeClock()
        rl = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=20_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        changed = asyncio.run(rl.update_limits(requests_per_minute=200, input_tokens_per_minute=30_000))
        assert changed is True
        assert rl._config.requests_per_minute == 200
        assert rl._config.input_tokens_per_minute == 50_000  # stayed (was higher)

    def test_none_values_ignored(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=20_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        changed = asyncio.run(rl.update_limits(requests_per_minute=None, input_tokens_per_minute=None))
        assert changed is False
        assert rl._config.requests_per_minute == 100


class TestAutoTuneFromHeaders:
    """Tests for header-based auto-tuning in RateLimitedProvider."""

    def test_anthropic_headers_trigger_update(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=50_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        result = CompletionResult(
            content="ok", tool_calls=[], input_tokens=10, output_tokens=5,
            model="test", stop_reason="end_turn",
            response_headers={
                "anthropic-ratelimit-requests-limit": "4000",
                "anthropic-ratelimit-tokens-limit": "200000",
            },
        )
        provider = SequenceProvider([result])
        wrapped = RateLimitedProvider(provider, limiter)

        async def run():
            await wrapped.complete(
                messages=[Message(role=MessageRole.USER, content="hi")],
                system=None,
                options=CompletionOptions(model="test", max_tokens=100),
            )

        asyncio.run(run())
        assert limiter._config.requests_per_minute == 4000
        assert limiter._config.input_tokens_per_minute == 200_000
        assert limiter._auto_tuned is True

    def test_no_headers_no_update(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(
            RateLimiterConfig(requests_per_minute=100, input_tokens_per_minute=50_000, output_tokens_per_minute=50_000, name="test"),
            now_fn=clock.now, sleep_fn=clock.sleep,
        )
        result = CompletionResult(
            content="ok", tool_calls=[], input_tokens=10, output_tokens=5,
            model="test", stop_reason="end_turn",
            response_headers=None,
        )
        provider = SequenceProvider([result])
        wrapped = RateLimitedProvider(provider, limiter)

        async def run():
            await wrapped.complete(
                messages=[Message(role=MessageRole.USER, content="hi")],
                system=None,
                options=CompletionOptions(model="test", max_tokens=100),
            )

        asyncio.run(run())
        assert limiter._config.requests_per_minute == 100
        assert limiter._auto_tuned is False
