"""Async leaky bucket rate limiter with RPM and separate input/output TPM constraints."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Floor headroom: block when token buckets fall below these thresholds,
# even when callers don't pass explicit estimates.
_MIN_INPUT_HEADROOM = 4_000   # ~avg file prompt size
_MIN_OUTPUT_HEADROOM = 1_000  # ~avg response size


@dataclass
class RateLimiterConfig:
    """Configuration for rate limiter with separate input/output token limits."""

    requests_per_minute: int = 60
    input_tokens_per_minute: int = 100_000
    output_tokens_per_minute: int = 100_000
    name: str = "default"


@dataclass
class UsageStats:
    """Current usage statistics from rate limiter."""

    request_count: int
    input_token_count: int
    output_token_count: int
    queue_size: int
    next_request_in_ms: float
    input_token_allowance: float
    output_token_allowance: float


# Provider defaults
ANTHROPIC_DEFAULTS = RateLimiterConfig(
    requests_per_minute=4000,
    input_tokens_per_minute=2_000_000,
    output_tokens_per_minute=400_000,
    name="anthropic",
)

OPENAI_DEFAULTS = RateLimiterConfig(
    requests_per_minute=500,
    input_tokens_per_minute=500_000,
    output_tokens_per_minute=500_000,
    name="openai",
)

GOOGLE_DEFAULTS = RateLimiterConfig(
    requests_per_minute=300,
    input_tokens_per_minute=5_000_000,
    output_tokens_per_minute=5_000_000,
    name="google",
)

_PROVIDER_DEFAULTS = {
    "anthropic": ANTHROPIC_DEFAULTS,
    "openai": OPENAI_DEFAULTS,
    "google": GOOGLE_DEFAULTS,
}


def get_default_config(provider: str) -> RateLimiterConfig:
    """Get default rate limiter config for a provider.

    Args:
        provider: Provider name (anthropic, openai, google)

    Returns:
        Default config for the provider

    Raises:
        ValueError: If provider is unknown
    """
    provider = provider.lower()
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unknown provider: {provider}. "
            f"Valid providers: {', '.join(_PROVIDER_DEFAULTS.keys())}"
        )
    config = _PROVIDER_DEFAULTS[provider]
    return RateLimiterConfig(
        requests_per_minute=config.requests_per_minute,
        input_tokens_per_minute=config.input_tokens_per_minute,
        output_tokens_per_minute=config.output_tokens_per_minute,
        name=config.name,
    )


def get_config_with_overrides(provider: str) -> RateLimiterConfig:
    """Get provider config with environment variable overrides.

    Environment variables checked:
        {PROVIDER}_RPM: Override requests_per_minute
        {PROVIDER}_INPUT_TPM: Override input_tokens_per_minute
        {PROVIDER}_OUTPUT_TPM: Override output_tokens_per_minute
        {PROVIDER}_TPM: Override both input and output (legacy, for backward compat)

    Args:
        provider: Provider name (anthropic, openai, google)

    Returns:
        Config with any env var overrides applied
    """
    config = get_default_config(provider)
    prefix = provider.upper()

    rpm_env = os.environ.get(f"{prefix}_RPM")
    if rpm_env is not None:
        try:
            config.requests_per_minute = int(rpm_env)
        except ValueError:
            logger.warning(f"Invalid {prefix}_RPM value: {rpm_env}, using default")

    # Legacy TPM override (sets both input and output)
    tpm_env = os.environ.get(f"{prefix}_TPM")
    if tpm_env is not None:
        try:
            tpm_value = int(tpm_env)
            config.input_tokens_per_minute = tpm_value
            config.output_tokens_per_minute = tpm_value
        except ValueError:
            logger.warning(f"Invalid {prefix}_TPM value: {tpm_env}, using default")

    # Specific input/output overrides (take precedence over legacy TPM)
    input_tpm_env = os.environ.get(f"{prefix}_INPUT_TPM")
    if input_tpm_env is not None:
        try:
            config.input_tokens_per_minute = int(input_tpm_env)
        except ValueError:
            logger.warning(f"Invalid {prefix}_INPUT_TPM value: {input_tpm_env}, using default")

    output_tpm_env = os.environ.get(f"{prefix}_OUTPUT_TPM")
    if output_tpm_env is not None:
        try:
            config.output_tokens_per_minute = int(output_tpm_env)
        except ValueError:
            logger.warning(f"Invalid {prefix}_OUTPUT_TPM value: {output_tpm_env}, using default")

    return config


class RateLimiter:
    """Async leaky bucket rate limiter with RPM and separate input/output TPM constraints.

    Implements a leaky bucket algorithm that enforces request rate (RPM)
    and separate input/output token rate (TPM) limits. Tokens refill continuously.

    Example:
        >>> limiter = RateLimiter(RateLimiterConfig(requests_per_minute=60))
        >>> await limiter.throttle()
        >>> # make API request
        >>> limiter.record_usage(input_tokens=1000, output_tokens=500)
    """

    def __init__(self, config: RateLimiterConfig) -> None:
        """Initialize rate limiter.

        Args:
            config: Rate limiter configuration
        """
        self._config = config
        self._lock = asyncio.Lock()

        # Compute intervals and rates
        self._request_interval_ms = 60_000 / config.requests_per_minute
        self._input_token_refill_rate = config.input_tokens_per_minute / 60_000
        self._output_token_refill_rate = config.output_tokens_per_minute / 60_000

        # Initialize state
        now = time.monotonic()
        self._last_request_time: float = 0.0
        self._last_refill_time: float = now
        self._window_start: float = now
        self._input_token_allowance: float = float(config.input_tokens_per_minute)
        self._output_token_allowance: float = float(config.output_tokens_per_minute)
        self._request_count: int = 0
        self._input_token_count: int = 0
        self._output_token_count: int = 0
        self._queue_size: int = 0

        # Cumulative counters (never reset with the 60s window)
        self._cumulative_input_tokens: int = 0
        self._cumulative_output_tokens: int = 0
        self._cumulative_request_count: int = 0

    async def throttle(
        self,
        estimated_input_tokens: Optional[int] = None,
        estimated_output_tokens: Optional[int] = None,
    ) -> None:
        """Wait for rate limit to allow a request.

        This method blocks until RPM and TPM constraints are satisfied.
        If estimated tokens are provided, also waits for sufficient capacity.

        Args:
            estimated_input_tokens: Optional estimate of input tokens
            estimated_output_tokens: Optional estimate of output tokens
        """
        self._queue_size += 1
        try:
            while True:
                async with self._lock:
                    wait_time = self._calculate_wait_time(
                        estimated_input_tokens, estimated_output_tokens
                    )
                    if wait_time <= 0:
                        # Can proceed - claim the slot
                        self._last_request_time = time.monotonic()
                        self._request_count += 1
                        self._cumulative_request_count += 1
                        return
                # Release lock before sleeping
                logger.info(
                    f"[{self._config.name}] Rate limit: waiting {wait_time*1000:.0f}ms"
                )
                await asyncio.sleep(wait_time)
        finally:
            self._queue_size -= 1

    def _calculate_wait_time(
        self,
        estimated_input_tokens: Optional[int],
        estimated_output_tokens: Optional[int],
    ) -> float:
        """Calculate how long to wait before proceeding (must hold lock).

        Returns seconds to wait, or 0 if can proceed immediately.
        """
        now = time.monotonic()

        # Reset window if 60s elapsed
        window_elapsed = now - self._window_start
        if window_elapsed >= 60.0:
            self._window_start = now
            self._request_count = 0
            self._input_token_count = 0
            self._output_token_count = 0

        # Refill tokens
        self._refill_tokens(now)

        wait_time = 0.0

        # Check RPM constraint
        if self._last_request_time > 0:
            elapsed = now - self._last_request_time
            interval_sec = self._request_interval_ms / 1000
            if elapsed < interval_sec:
                wait_time = max(wait_time, interval_sec - elapsed)

        # Check input TPM constraint
        if estimated_input_tokens is not None and estimated_input_tokens > 0:
            if self._input_token_allowance < estimated_input_tokens:
                tokens_needed = estimated_input_tokens - self._input_token_allowance
                wait_time = max(wait_time, tokens_needed / self._input_token_refill_rate / 1000)

        # Check output TPM constraint
        if estimated_output_tokens is not None and estimated_output_tokens > 0:
            if self._output_token_allowance < estimated_output_tokens:
                tokens_needed = estimated_output_tokens - self._output_token_allowance
                wait_time = max(wait_time, tokens_needed / self._output_token_refill_rate / 1000)

        # Floor check: block if buckets are depleted even without estimates
        if estimated_input_tokens is None and estimated_output_tokens is None:
            if self._input_token_allowance < _MIN_INPUT_HEADROOM:
                tokens_needed = _MIN_INPUT_HEADROOM - self._input_token_allowance
                wait_time = max(wait_time, tokens_needed / self._input_token_refill_rate / 1000)
            if self._output_token_allowance < _MIN_OUTPUT_HEADROOM:
                tokens_needed = _MIN_OUTPUT_HEADROOM - self._output_token_allowance
                wait_time = max(wait_time, tokens_needed / self._output_token_refill_rate / 1000)

        return wait_time

    def _refill_tokens(self, now: float) -> None:
        """Refill token buckets based on elapsed time (must hold lock)."""
        elapsed_ms = (now - self._last_refill_time) * 1000

        input_refill = elapsed_ms * self._input_token_refill_rate
        self._input_token_allowance = min(
            self._input_token_allowance + input_refill,
            float(self._config.input_tokens_per_minute),
        )

        output_refill = elapsed_ms * self._output_token_refill_rate
        self._output_token_allowance = min(
            self._output_token_allowance + output_refill,
            float(self._config.output_tokens_per_minute),
        )

        self._last_refill_time = now

    def record_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record token usage after a request completes.

        This deducts tokens from the allowance buckets.

        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
        """

        # Warn for large input token usage (>10% of input TPM)
        if input_tokens > self._config.input_tokens_per_minute * 0.1:
            logger.warning(
                f"[{self._config.name}] Large input token usage: {input_tokens} tokens "
                f"(>{self._config.input_tokens_per_minute * 0.1:.0f}, 10% of input TPM)"
            )

        # Warn for large output token usage (>10% of output TPM)
        if output_tokens > self._config.output_tokens_per_minute * 0.1:
            logger.warning(
                f"[{self._config.name}] Large output token usage: {output_tokens} tokens "
                f"(>{self._config.output_tokens_per_minute * 0.1:.0f}, 10% of output TPM)"
            )

        self._input_token_allowance = max(0.0, self._input_token_allowance - input_tokens)
        self._output_token_allowance = max(0.0, self._output_token_allowance - output_tokens)
        self._input_token_count += input_tokens
        self._output_token_count += output_tokens
        self._cumulative_input_tokens += input_tokens
        self._cumulative_output_tokens += output_tokens

    def get_cumulative_tokens(self) -> tuple[int, int]:
        """Return (total_input_tokens, total_output_tokens) across all time."""
        return (self._cumulative_input_tokens, self._cumulative_output_tokens)

    def can_proceed(self) -> bool:
        """Synchronous check if a request can proceed immediately.

        Returns:
            True if RPM and TPM constraints are satisfied
        """
        now = time.monotonic()

        # Check RPM constraint
        if self._last_request_time > 0:
            elapsed_ms = (now - self._last_request_time) * 1000
            if elapsed_ms < self._request_interval_ms:
                return False

        # Check we have at least some token allowance in both buckets
        if self._input_token_allowance <= 0 or self._output_token_allowance <= 0:
            return False

        return True

    def get_stats(self) -> UsageStats:
        """Get current usage statistics.

        Returns:
            Current statistics including counts, queue size, and timing info
        """
        now = time.monotonic()

        # Calculate next request time
        next_request_in_ms = 0.0
        if self._last_request_time > 0:
            elapsed_ms = (now - self._last_request_time) * 1000
            remaining_ms = self._request_interval_ms - elapsed_ms
            next_request_in_ms = max(0.0, remaining_ms)

        return UsageStats(
            request_count=self._request_count,
            input_token_count=self._input_token_count,
            output_token_count=self._output_token_count,
            queue_size=self._queue_size,
            next_request_in_ms=next_request_in_ms,
            input_token_allowance=self._input_token_allowance,
            output_token_allowance=self._output_token_allowance,
        )

    def reset(self) -> None:
        """Reset all state to initial values."""
        now = time.monotonic()
        self._last_request_time = 0.0
        self._last_refill_time = now
        self._window_start = now
        self._input_token_allowance = float(self._config.input_tokens_per_minute)
        self._output_token_allowance = float(self._config.output_tokens_per_minute)
        self._request_count = 0
        self._input_token_count = 0
        self._output_token_count = 0
        self._cumulative_input_tokens = 0
        self._cumulative_output_tokens = 0
        self._cumulative_request_count = 0
        # Note: _queue_size not reset as it tracks active waiters
