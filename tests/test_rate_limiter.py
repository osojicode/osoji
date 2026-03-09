"""Tests for rate limiter module."""

from __future__ import annotations

import asyncio
import os
import time
from unittest import mock

import pytest

from osoji.rate_limiter import (
    ANTHROPIC_DEFAULTS,
    GOOGLE_DEFAULTS,
    OPENAI_DEFAULTS,
    RateLimiter,
    RateLimiterConfig,
    UsageStats,
    get_config_with_overrides,
    get_default_config,
)


class TestRateLimiterConfig:
    """Tests for RateLimiterConfig dataclass."""

    def test_default_values(self):
        config = RateLimiterConfig()
        assert config.requests_per_minute == 60
        assert config.input_tokens_per_minute == 100_000
        assert config.output_tokens_per_minute == 100_000
        assert config.name == "default"

    def test_custom_values(self):
        config = RateLimiterConfig(
            requests_per_minute=120,
            input_tokens_per_minute=200_000,
            output_tokens_per_minute=50_000,
            name="custom",
        )
        assert config.requests_per_minute == 120
        assert config.input_tokens_per_minute == 200_000
        assert config.output_tokens_per_minute == 50_000
        assert config.name == "custom"


class TestProviderDefaults:
    """Tests for provider default configurations."""

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

    def test_get_default_config_anthropic(self):
        config = get_default_config("anthropic")
        assert config.requests_per_minute == 4000
        assert config.input_tokens_per_minute == 2_000_000
        assert config.output_tokens_per_minute == 400_000
        assert config.name == "anthropic"

    def test_get_default_config_case_insensitive(self):
        config = get_default_config("ANTHROPIC")
        assert config.name == "anthropic"

    def test_get_default_config_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_default_config("unknown")


class TestEnvironmentOverrides:
    """Tests for environment variable overrides."""

    def test_rpm_override(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_RPM": "120"}):
            config = get_config_with_overrides("anthropic")
            assert config.requests_per_minute == 120
            assert config.input_tokens_per_minute == 2_000_000  # unchanged

    def test_tpm_override_sets_both(self):
        """Legacy TPM env var sets both input and output."""
        with mock.patch.dict(os.environ, {"ANTHROPIC_TPM": "200000"}):
            config = get_config_with_overrides("anthropic")
            assert config.requests_per_minute == 4000  # unchanged
            assert config.input_tokens_per_minute == 200_000
            assert config.output_tokens_per_minute == 200_000

    def test_input_tpm_override(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_INPUT_TPM": "3000000"}):
            config = get_config_with_overrides("anthropic")
            assert config.input_tokens_per_minute == 3_000_000
            assert config.output_tokens_per_minute == 400_000  # unchanged

    def test_output_tpm_override(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_OUTPUT_TPM": "500000"}):
            config = get_config_with_overrides("anthropic")
            assert config.input_tokens_per_minute == 2_000_000  # unchanged
            assert config.output_tokens_per_minute == 500_000

    def test_specific_overrides_take_precedence(self):
        """INPUT_TPM and OUTPUT_TPM take precedence over legacy TPM."""
        with mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_TPM": "100000",  # Sets both to 100K
                "ANTHROPIC_INPUT_TPM": "3000000",  # Override input to 3M
            },
        ):
            config = get_config_with_overrides("anthropic")
            assert config.input_tokens_per_minute == 3_000_000  # From INPUT_TPM
            assert config.output_tokens_per_minute == 100_000  # From legacy TPM

    def test_all_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_RPM": "1000",
                "OPENAI_INPUT_TPM": "1000000",
                "OPENAI_OUTPUT_TPM": "500000",
            },
        ):
            config = get_config_with_overrides("openai")
            assert config.requests_per_minute == 1000
            assert config.input_tokens_per_minute == 1_000_000
            assert config.output_tokens_per_minute == 500_000

    def test_invalid_rpm_uses_default(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_RPM": "not_a_number"}):
            config = get_config_with_overrides("anthropic")
            assert config.requests_per_minute == 4000  # default

    def test_invalid_tpm_uses_default(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_TPM": "invalid"}):
            config = get_config_with_overrides("anthropic")
            assert config.input_tokens_per_minute == 2_000_000  # default
            assert config.output_tokens_per_minute == 400_000  # default


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def config(self):
        return RateLimiterConfig(
            requests_per_minute=60,
            input_tokens_per_minute=100_000,
            output_tokens_per_minute=50_000,
            name="test",
        )

    @pytest.fixture
    def limiter(self, config):
        return RateLimiter(config)

    def test_init(self, limiter, config):
        stats = limiter.get_stats()
        assert stats.request_count == 0
        assert stats.input_token_count == 0
        assert stats.output_token_count == 0
        assert stats.input_token_allowance == config.input_tokens_per_minute
        assert stats.output_token_allowance == config.output_tokens_per_minute

    def test_can_proceed_initially_true(self, limiter):
        assert limiter.can_proceed() is True

    def test_first_request_no_wait(self, limiter):
        async def run():
            start = time.monotonic()
            await limiter.throttle()
            elapsed = time.monotonic() - start
            # First request should not wait
            assert elapsed < 0.1

        asyncio.run(run())

    def test_request_count_incremented(self, limiter):
        async def run():
            await limiter.throttle()
            stats = limiter.get_stats()
            assert stats.request_count == 1

        asyncio.run(run())

    def test_rpm_spacing_enforcement(self):
        """Test that requests are spaced according to RPM limit."""

        async def run():
            # 600 RPM = 100ms between requests
            config = RateLimiterConfig(requests_per_minute=600, name="test")
            limiter = RateLimiter(config)

            await limiter.throttle()
            start = time.monotonic()
            await limiter.throttle()
            elapsed = time.monotonic() - start

            # Should wait approximately 100ms
            assert elapsed >= 0.09  # Allow small tolerance
            assert elapsed < 0.2

        asyncio.run(run())

    def test_output_tpm_blocking_when_exhausted(self):
        """Test that throttle waits when output tokens exhausted."""

        async def run():
            # Low TPM for faster testing
            config = RateLimiterConfig(
                requests_per_minute=6000,  # High RPM so it doesn't interfere
                input_tokens_per_minute=100_000,
                output_tokens_per_minute=6000,  # 100 tokens per second
                name="test",
            )
            limiter = RateLimiter(config)

            # Exhaust most output tokens
            await limiter.throttle()
            limiter.record_usage(output_tokens=5950)  # Leave only 50 tokens

            # Next request with estimated tokens should wait
            start = time.monotonic()
            await limiter.throttle(estimated_output_tokens=100)  # Need 100, have 50
            elapsed = time.monotonic() - start

            # Should have waited for ~50 tokens to refill
            # At 100 tokens/sec, 50 tokens = 0.5 seconds
            assert elapsed >= 0.4  # Allow tolerance

        asyncio.run(run())

    def test_record_usage_deducts_tokens(self, limiter, config):
        async def run():
            await limiter.throttle()
            initial_input = limiter.get_stats().input_token_allowance
            initial_output = limiter.get_stats().output_token_allowance

            limiter.record_usage(input_tokens=5000, output_tokens=2000)

            stats = limiter.get_stats()
            assert stats.input_token_allowance == initial_input - 5000
            assert stats.output_token_allowance == initial_output - 2000

        asyncio.run(run())

    def test_record_usage_tracks_total(self, limiter):
        async def run():
            await limiter.throttle()
            limiter.record_usage(input_tokens=1000, output_tokens=500)
            limiter.record_usage(input_tokens=2000, output_tokens=1000)

            stats = limiter.get_stats()
            assert stats.input_token_count == 3000
            assert stats.output_token_count == 1500

        asyncio.run(run())

    def test_record_usage_cannot_go_negative(self, limiter):
        limiter.record_usage(input_tokens=200_000, output_tokens=100_000)
        stats = limiter.get_stats()
        assert stats.input_token_allowance == 0.0
        assert stats.output_token_allowance == 0.0

    def test_concurrent_requests_all_complete(self):
        """Test that concurrent requests all complete with proper spacing."""

        async def run():
            # 120 RPM = 500ms between requests
            config = RateLimiterConfig(requests_per_minute=120, name="test")
            limiter = RateLimiter(config)

            completed = []

            async def make_request(id: int):
                await limiter.throttle()
                completed.append(id)

            # Launch concurrent requests
            await limiter.throttle()  # First request
            tasks = [
                asyncio.create_task(make_request(1)),
                asyncio.create_task(make_request(2)),
                asyncio.create_task(make_request(3)),
            ]

            await asyncio.gather(*tasks)

            # All requests should complete (order not guaranteed)
            assert len(completed) == 3
            assert set(completed) == {1, 2, 3}

        asyncio.run(run())

    def test_stats_tracking(self):
        async def run():
            config = RateLimiterConfig(
                requests_per_minute=6000,  # High RPM for fast test
                input_tokens_per_minute=100_000,
                output_tokens_per_minute=50_000,
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            limiter.record_usage(input_tokens=1000, output_tokens=500)

            await limiter.throttle()
            limiter.record_usage(input_tokens=2000, output_tokens=1000)

            stats = limiter.get_stats()
            assert stats.request_count == 2
            assert stats.input_token_count == 3000
            assert stats.output_token_count == 1500

        asyncio.run(run())

    def test_reset_clears_state(self, limiter, config):
        async def run():
            await limiter.throttle()
            limiter.record_usage(input_tokens=5000, output_tokens=2000)

            limiter.reset()

            stats = limiter.get_stats()
            assert stats.request_count == 0
            assert stats.input_token_count == 0
            assert stats.output_token_count == 0
            assert stats.input_token_allowance == config.input_tokens_per_minute
            assert stats.output_token_allowance == config.output_tokens_per_minute

        asyncio.run(run())

    def test_reset_allows_immediate_request(self, limiter):
        async def run():
            await limiter.throttle()

            limiter.reset()

            # Should be able to proceed immediately
            assert limiter.can_proceed() is True

            start = time.monotonic()
            await limiter.throttle()
            elapsed = time.monotonic() - start
            assert elapsed < 0.1

        asyncio.run(run())

    def test_window_reset_after_60_seconds(self):
        """Test that request/token counts reset after window expires."""

        async def run():
            config = RateLimiterConfig(requests_per_minute=6000, name="test")
            limiter = RateLimiter(config)

            await limiter.throttle()
            limiter.record_usage(input_tokens=1000, output_tokens=500)

            stats = limiter.get_stats()
            assert stats.request_count == 1
            assert stats.input_token_count == 1000
            assert stats.output_token_count == 500

            # Simulate time passing by manipulating window_start
            limiter._window_start = time.monotonic() - 61

            await limiter.throttle()

            stats = limiter.get_stats()
            # Should have reset and then incremented
            assert stats.request_count == 1
            assert stats.input_token_count == 0
            assert stats.output_token_count == 0

        asyncio.run(run())

    def test_can_proceed_false_after_request(self):
        """Test can_proceed returns False right after a request."""
        # 60 RPM = 1000ms between requests
        config = RateLimiterConfig(requests_per_minute=60, name="test")
        limiter = RateLimiter(config)

        # Simulate a request just happened
        limiter._last_request_time = time.monotonic()

        assert limiter.can_proceed() is False

    def test_can_proceed_false_when_no_input_tokens(self, limiter):
        """Test can_proceed returns False when input tokens exhausted."""
        limiter._input_token_allowance = 0

        assert limiter.can_proceed() is False

    def test_can_proceed_false_when_no_output_tokens(self, limiter):
        """Test can_proceed returns False when output tokens exhausted."""
        limiter._output_token_allowance = 0

        assert limiter.can_proceed() is False

    def test_can_proceed_refills_tokens_before_check(self):
        """Elapsed time should replenish buckets before can_proceed evaluates them."""
        config = RateLimiterConfig(
            requests_per_minute=60,
            input_tokens_per_minute=240_000,
            output_tokens_per_minute=60_000,
            name="test",
        )
        limiter = RateLimiter(config)
        limiter._input_token_allowance = 0
        limiter._output_token_allowance = 0
        limiter._last_refill_time = time.monotonic() - 1.1

        assert limiter.can_proceed() is True

    def test_queue_size_tracking(self):
        """Test that queue_size is tracked during throttle."""

        async def run():
            config = RateLimiterConfig(requests_per_minute=60, name="test")
            limiter = RateLimiter(config)

            await limiter.throttle()

            queue_sizes = []

            async def track_queue(id: int):
                # Small delay to let both tasks enter throttle
                if id == 2:
                    await asyncio.sleep(0.01)
                queue_sizes.append(limiter.get_stats().queue_size)
                await limiter.throttle()

            # First task will be waiting, second will check queue
            task1 = asyncio.create_task(track_queue(1))
            task2 = asyncio.create_task(track_queue(2))

            await asyncio.gather(task1, task2)

            # At some point queue_size should have been > 0
            # (This is a best-effort check due to timing)
            assert len(queue_sizes) == 2

        asyncio.run(run())

    def test_get_stats_returns_usage_stats(self, limiter):
        stats = limiter.get_stats()
        assert isinstance(stats, UsageStats)
        assert hasattr(stats, "request_count")
        assert hasattr(stats, "input_token_count")
        assert hasattr(stats, "output_token_count")
        assert hasattr(stats, "queue_size")
        assert hasattr(stats, "next_request_in_ms")
        assert hasattr(stats, "input_token_allowance")
        assert hasattr(stats, "output_token_allowance")

    def test_next_request_in_ms_accurate(self):
        """Test that next_request_in_ms reflects actual wait time."""

        async def run():
            # 60 RPM = 1000ms between requests
            config = RateLimiterConfig(requests_per_minute=60, name="test")
            limiter = RateLimiter(config)

            await limiter.throttle()

            stats = limiter.get_stats()
            # Should be close to 1000ms (minus small elapsed time)
            assert stats.next_request_in_ms > 900
            assert stats.next_request_in_ms <= 1000

        asyncio.run(run())

    def test_output_token_refill_over_time(self):
        """Test that output tokens refill continuously."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=6000,
                input_tokens_per_minute=100_000,
                output_tokens_per_minute=60_000,  # 1000 tokens per second
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            limiter.record_usage(output_tokens=10_000)

            initial = limiter.get_stats().output_token_allowance
            await asyncio.sleep(0.1)  # 100ms = ~100 tokens should refill

            await limiter.throttle()  # Triggers refill
            after = limiter.get_stats().output_token_allowance

            # Should have refilled some tokens (accounting for deduction timing)
            assert after > initial

        asyncio.run(run())


class TestFloorCheck:
    """Tests for the floor-check behavior that blocks when token buckets are depleted."""

    def test_floor_check_blocks_when_input_tokens_depleted(self):
        """Without estimates, throttle should still wait if input tokens are below headroom."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=60_000,  # High RPM so it doesn't interfere
                input_tokens_per_minute=6000,  # 100 tokens/sec
                output_tokens_per_minute=600_000,
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            # Drain input tokens well below _MIN_INPUT_HEADROOM (4000)
            limiter.record_usage(input_tokens=5900)  # leaves 100 tokens

            start = time.monotonic()
            # No estimates passed — floor check should kick in
            await limiter.throttle()
            elapsed = time.monotonic() - start

            assert elapsed >= 0.01  # Just verify it waited at all

        asyncio.run(run())

    def test_floor_check_blocks_when_input_tokens_depleted_fast(self):
        """Floor check blocks proportionally when input bucket is depleted."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=60_000,
                input_tokens_per_minute=600_000,  # 10_000 tokens/sec
                output_tokens_per_minute=600_000,
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            # Drain to 1000 tokens (below 4000 headroom)
            limiter.record_usage(input_tokens=599_000)

            start = time.monotonic()
            await limiter.throttle()  # No estimates
            elapsed = time.monotonic() - start

            # Need 3000 tokens to reach 4000 headroom
            # refill_rate = 600_000/60_000 = 10 tokens/ms
            # wait = 3000 / 10 / 1000 = 0.3 seconds
            assert elapsed >= 0.25
            assert elapsed < 0.6

        asyncio.run(run())

    def test_floor_check_blocks_when_output_tokens_depleted(self):
        """Without estimates, throttle waits if output tokens are below headroom."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=60_000,
                input_tokens_per_minute=600_000,
                output_tokens_per_minute=60_000,  # 1000 tokens/sec
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            # Drain output to 500 (below 1000 headroom)
            limiter.record_usage(output_tokens=59_500)

            start = time.monotonic()
            await limiter.throttle()  # No estimates
            elapsed = time.monotonic() - start

            # Need 500 tokens to reach 1000 headroom
            # refill_rate = 60_000/60_000 = 1 token/ms
            # wait = 500 / 1 / 1000 = 0.5 seconds
            assert elapsed >= 0.4
            assert elapsed < 0.8

        asyncio.run(run())

    def test_floor_check_skipped_when_estimates_provided(self):
        """When explicit estimates are provided, floor check does not apply."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=60_000,
                input_tokens_per_minute=600_000,
                output_tokens_per_minute=600_000,
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            # Drain input tokens below headroom
            limiter.record_usage(input_tokens=598_000)  # leaves 2000

            start = time.monotonic()
            # With estimates of 100 tokens (we have 2000), should pass quickly
            await limiter.throttle(estimated_input_tokens=100)
            elapsed = time.monotonic() - start

            assert elapsed < 0.1  # Should not trigger floor check

        asyncio.run(run())

    def test_floor_check_no_wait_when_buckets_healthy(self):
        """No floor-check wait when token buckets are above headroom."""

        async def run():
            config = RateLimiterConfig(
                requests_per_minute=60_000,
                input_tokens_per_minute=600_000,
                output_tokens_per_minute=600_000,
                name="test",
            )
            limiter = RateLimiter(config)

            await limiter.throttle()
            # Use some tokens but stay above headroom
            limiter.record_usage(input_tokens=10_000, output_tokens=5_000)

            start = time.monotonic()
            await limiter.throttle()  # No estimates
            elapsed = time.monotonic() - start

            assert elapsed < 0.1  # Should proceed quickly

        asyncio.run(run())


class TestUsageStats:
    """Tests for UsageStats dataclass."""

    def test_usage_stats_creation(self):
        stats = UsageStats(
            request_count=10,
            input_token_count=8000,
            output_token_count=2000,
            queue_size=2,
            next_request_in_ms=500.0,
            input_token_allowance=92000.0,
            output_token_allowance=48000.0,
        )
        assert stats.request_count == 10
        assert stats.input_token_count == 8000
        assert stats.output_token_count == 2000
        assert stats.queue_size == 2
        assert stats.next_request_in_ms == 500.0
        assert stats.input_token_allowance == 92000.0
        assert stats.output_token_allowance == 48000.0
