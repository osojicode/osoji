"""Reservation-based async rate limiter with RPM and separate input/output TPM limits."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .llm.registry import normalize_provider_name

logger = logging.getLogger(__name__)

_OUTPUT_HISTORY_LIMIT = 20
_OUTPUT_WARMUP_SAMPLES = 5
_MIN_OUTPUT_RESERVATION = 128
_CONSERVATIVE_RESET_SAMPLES = 5
_UNDER_RESERVED_WARMUP_SAMPLES = 2
_INPUT_SAFETY_MULTIPLIER = 1.15


@dataclass
class RateLimiterConfig:
    """Configuration for rate limiter with separate input/output token limits."""

    requests_per_minute: int = 60
    input_tokens_per_minute: int = 100_000
    output_tokens_per_minute: int = 100_000
    name: str = "default"


@dataclass
class ReservationTicket:
    """Reservation captured before an LLM request is admitted."""

    ticket_id: int
    reservation_key: str
    reserved_input_tokens: int
    reserved_output_tokens: int
    acquired_at: float


@dataclass
class ReservationProfile:
    """Adaptive output reservation profile for a logical request type."""

    output_history: deque[int] = field(
        default_factory=lambda: deque(maxlen=_OUTPUT_HISTORY_LIMIT)
    )
    conservative_remaining: int = _OUTPUT_WARMUP_SAMPLES
    under_reserved_count: int = 0
    rate_limit_hits: int = 0


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
    inflight_requests: int
    inflight_reserved_input_tokens: int
    inflight_reserved_output_tokens: int
    input_headroom_pct: float
    output_headroom_pct: float
    peak_rpm_utilization_pct: float
    peak_input_utilization_pct: float
    peak_output_utilization_pct: float
    cumulative_reserved_input_tokens: int
    cumulative_reserved_output_tokens: int
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    rate_limit_retries: int
    under_reserved_count: int


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

OPENROUTER_DEFAULTS = RateLimiterConfig(
    requests_per_minute=300,
    input_tokens_per_minute=500_000,
    output_tokens_per_minute=500_000,
    name="openrouter",
)

_PROVIDER_DEFAULTS = {
    "anthropic": ANTHROPIC_DEFAULTS,
    "openai": OPENAI_DEFAULTS,
    "google": GOOGLE_DEFAULTS,
    "openrouter": OPENROUTER_DEFAULTS,
}


def get_default_config(provider: str) -> RateLimiterConfig:
    """Get default rate limiter config for a provider."""

    provider = normalize_provider_name(provider)
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
    """Get provider config with environment variable overrides."""

    config = get_default_config(provider)
    prefix = provider.upper()

    rpm_env = os.environ.get(f"{prefix}_RPM")
    if rpm_env is not None:
        try:
            config.requests_per_minute = int(rpm_env)
        except ValueError:
            logger.warning("Invalid %s_RPM value: %s, using default", prefix, rpm_env)

    tpm_env = os.environ.get(f"{prefix}_TPM")
    if tpm_env is not None:
        try:
            tpm_value = int(tpm_env)
            config.input_tokens_per_minute = tpm_value
            config.output_tokens_per_minute = tpm_value
        except ValueError:
            logger.warning("Invalid %s_TPM value: %s, using default", prefix, tpm_env)

    input_tpm_env = os.environ.get(f"{prefix}_INPUT_TPM")
    if input_tpm_env is not None:
        try:
            config.input_tokens_per_minute = int(input_tpm_env)
        except ValueError:
            logger.warning(
                "Invalid %s_INPUT_TPM value: %s, using default",
                prefix,
                input_tpm_env,
            )

    output_tpm_env = os.environ.get(f"{prefix}_OUTPUT_TPM")
    if output_tpm_env is not None:
        try:
            config.output_tokens_per_minute = int(output_tpm_env)
        except ValueError:
            logger.warning(
                "Invalid %s_OUTPUT_TPM value: %s, using default",
                prefix,
                output_tpm_env,
            )

    # Clamp to minimum 1 to prevent division-by-zero in interval calculations
    config.requests_per_minute = max(1, config.requests_per_minute)
    config.input_tokens_per_minute = max(1, config.input_tokens_per_minute)
    config.output_tokens_per_minute = max(1, config.output_tokens_per_minute)

    return config


class RateLimiter:
    """Async reservation-based limiter for RPM plus input/output TPM budgets."""

    def __init__(
        self,
        config: RateLimiterConfig,
        *,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._now = now_fn or time.monotonic
        self._sleep = sleep_fn or asyncio.sleep

        self._request_interval_ms = 60_000 / config.requests_per_minute
        self._input_token_refill_rate = config.input_tokens_per_minute / 60_000
        self._output_token_refill_rate = config.output_tokens_per_minute / 60_000

        now = self._now()
        self._last_request_time = 0.0
        self._last_refill_time = now
        self._window_start = now
        self._cooldown_until = 0.0

        self._input_token_allowance = float(config.input_tokens_per_minute)
        self._output_token_allowance = float(config.output_tokens_per_minute)
        self._request_count = 0
        self._input_token_count = 0
        self._output_token_count = 0
        self._queue_size = 0

        self._cumulative_input_tokens = 0
        self._cumulative_output_tokens = 0
        self._cumulative_request_count = 0
        self._cumulative_reserved_input_tokens = 0
        self._cumulative_reserved_output_tokens = 0

        self._peak_rpm_utilization_pct = 0.0
        self._peak_input_utilization_pct = 0.0
        self._peak_output_utilization_pct = 0.0
        self._rate_limit_retries = 0
        self._under_reserved_count = 0

        self._next_ticket_id = 1
        self._inflight: dict[int, ReservationTicket] = {}
        self._inflight_reserved_input_tokens = 0
        self._inflight_reserved_output_tokens = 0
        self._profiles: dict[str, ReservationProfile] = {}
        self._auto_tuned: bool = False

    @property
    def input_safety_multiplier(self) -> float:
        return _INPUT_SAFETY_MULTIPLIER

    async def update_limits(
        self,
        *,
        requests_per_minute: int | None = None,
        input_tokens_per_minute: int | None = None,
        output_tokens_per_minute: int | None = None,
    ) -> bool:
        """Update rate limits upward based on discovered provider capacity.

        Only increases limits (never reduces below current config).
        No-op after the first successful call (auto-tunes once per instance).
        Returns True if any limit was changed.
        """
        async with self._lock:
            if self._auto_tuned:
                return False
            changed = False

            if requests_per_minute is not None and requests_per_minute > self._config.requests_per_minute:
                logger.info(
                    "[%s] Auto-tuning RPM: %d -> %d",
                    self._config.name,
                    self._config.requests_per_minute,
                    requests_per_minute,
                )
                self._config.requests_per_minute = requests_per_minute
                self._request_interval_ms = 60_000 / requests_per_minute
                changed = True

            if input_tokens_per_minute is not None and input_tokens_per_minute > self._config.input_tokens_per_minute:
                logger.info(
                    "[%s] Auto-tuning input TPM: %d -> %d",
                    self._config.name,
                    self._config.input_tokens_per_minute,
                    input_tokens_per_minute,
                )
                self._config.input_tokens_per_minute = input_tokens_per_minute
                self._input_token_refill_rate = input_tokens_per_minute / 60_000
                self._input_token_allowance = min(
                    self._input_token_allowance, float(input_tokens_per_minute),
                )
                changed = True

            if output_tokens_per_minute is not None and output_tokens_per_minute > self._config.output_tokens_per_minute:
                logger.info(
                    "[%s] Auto-tuning output TPM: %d -> %d",
                    self._config.name,
                    self._config.output_tokens_per_minute,
                    output_tokens_per_minute,
                )
                self._config.output_tokens_per_minute = output_tokens_per_minute
                self._output_token_refill_rate = output_tokens_per_minute / 60_000
                self._output_token_allowance = min(
                    self._output_token_allowance, float(output_tokens_per_minute),
                )
                changed = True

            if changed:
                self._auto_tuned = True
            return changed

    async def acquire(
        self,
        *,
        reservation_key: str,
        estimated_input_tokens: int,
        reserved_output_tokens: int | None,
        max_output_tokens: int,
    ) -> ReservationTicket:
        """Wait until RPM/TPM budgets are available, then reserve them."""

        reservation_key = reservation_key or "default"
        estimated_input_tokens = max(0, int(estimated_input_tokens))
        max_output_tokens = max(0, int(max_output_tokens))
        explicit_output = (
            None if reserved_output_tokens is None else max(0, int(reserved_output_tokens))
        )

        self._queue_size += 1
        try:
            while True:
                async with self._lock:
                    now = self._now()
                    self._refresh_window(now)
                    self._refill_tokens(now)

                    output_tokens = self._select_output_reservation(
                        reservation_key,
                        explicit_output,
                        max_output_tokens,
                    )
                    wait_time = self._calculate_wait_time(
                        now=now,
                        requested_input_tokens=estimated_input_tokens,
                        requested_output_tokens=output_tokens,
                    )
                    if wait_time <= 0:
                        ticket = self._claim_reservation(
                            now=now,
                            reservation_key=reservation_key,
                            reserved_input_tokens=estimated_input_tokens,
                            reserved_output_tokens=output_tokens,
                        )
                        return ticket

                logger.info(
                    "[%s] Rate limit: waiting %.0fms",
                    self._config.name,
                    wait_time * 1000,
                )
                await self._sleep(wait_time)
        finally:
            self._queue_size -= 1

    async def finalize_success(
        self,
        ticket: ReservationTicket,
        *,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> UsageStats:
        """Reconcile a successful request against its earlier reservation."""

        async with self._lock:
            now = self._now()
            self._refresh_window(now)
            self._refill_tokens(now)

            popped = self._pop_ticket(ticket)
            actual_input_tokens = max(0, int(actual_input_tokens))
            actual_output_tokens = max(0, int(actual_output_tokens))

            self._input_token_allowance = self._apply_actual_tokens(
                allowance=self._input_token_allowance,
                capacity=float(self._config.input_tokens_per_minute),
                reserved_tokens=popped.reserved_input_tokens,
                actual_tokens=actual_input_tokens,
            )
            self._output_token_allowance = self._apply_actual_tokens(
                allowance=self._output_token_allowance,
                capacity=float(self._config.output_tokens_per_minute),
                reserved_tokens=popped.reserved_output_tokens,
                actual_tokens=actual_output_tokens,
            )

            self._input_token_count += actual_input_tokens
            self._output_token_count += actual_output_tokens
            self._cumulative_input_tokens += actual_input_tokens
            self._cumulative_output_tokens += actual_output_tokens

            profile = self._profile_for(popped.reservation_key)
            profile.output_history.append(actual_output_tokens)
            if profile.conservative_remaining > 0:
                profile.conservative_remaining -= 1
            if actual_output_tokens > popped.reserved_output_tokens:
                profile.under_reserved_count += 1
                profile.conservative_remaining = max(
                    profile.conservative_remaining,
                    _UNDER_RESERVED_WARMUP_SAMPLES,
                )
                self._under_reserved_count += 1

            self._update_peak_utilization()
            return self._build_stats(now)

    async def finalize_failure(
        self,
        ticket: ReservationTicket,
        *,
        is_rate_limit: bool,
        retry_after: float | None = None,
    ) -> UsageStats:
        """Handle a failed request, refunding or cooling down as appropriate."""

        async with self._lock:
            now = self._now()
            self._refresh_window(now)
            self._refill_tokens(now)

            popped = self._pop_ticket(ticket)
            if is_rate_limit:
                profile = self._profile_for(popped.reservation_key)
                profile.rate_limit_hits += 1
                profile.conservative_remaining = max(
                    profile.conservative_remaining,
                    _CONSERVATIVE_RESET_SAMPLES,
                )
                self._rate_limit_retries += 1
                if retry_after is not None:
                    self._cooldown_until = max(self._cooldown_until, now + max(0.0, retry_after))
            else:
                self._refund_full(popped)

            self._update_peak_utilization()
            return self._build_stats(now)

    def get_cumulative_tokens(self) -> tuple[int, int]:
        """Return cumulative actual input/output tokens."""

        return (self._cumulative_input_tokens, self._cumulative_output_tokens)

    def get_stats(self) -> UsageStats:
        """Get current usage statistics without mutating limiter state."""

        return self._build_stats(self._now())

    def get_summary(self) -> str:
        """Return a human-readable summary of limiter behavior for this run."""

        reserved_total = (
            self._cumulative_reserved_input_tokens + self._cumulative_reserved_output_tokens
        )
        actual_total = self._cumulative_input_tokens + self._cumulative_output_tokens
        efficiency_pct = (
            (actual_total / reserved_total) * 100.0 if reserved_total else 100.0
        )

        lines = [
            (
                "Rate limit: "
                f"reserved={self._format_tokens(self._cumulative_reserved_input_tokens)}^ "
                f"{self._format_tokens(self._cumulative_reserved_output_tokens)}v | "
                f"actual={self._format_tokens(self._cumulative_input_tokens)}^ "
                f"{self._format_tokens(self._cumulative_output_tokens)}v | "
                f"efficiency={efficiency_pct:.0f}%"
            ),
            (
                "Headroom: "
                f"peak RPM={self._peak_rpm_utilization_pct:.0f}% | "
                f"peak input={self._peak_input_utilization_pct:.0f}% | "
                f"peak output={self._peak_output_utilization_pct:.0f}% | "
                f"rate-limit retries={self._rate_limit_retries}"
            ),
        ]

        hot_keys = sorted(
            (
                (key, profile.under_reserved_count)
                for key, profile in self._profiles.items()
                if profile.under_reserved_count > 0
            ),
            key=lambda item: (-item[1], item[0]),
        )[:5]
        if hot_keys:
            lines.append(
                "Under-reserved: "
                + ", ".join(f"{key}={count}" for key, count in hot_keys)
            )

        return "\n".join(lines)

    def _calculate_wait_time(
        self,
        *,
        now: float,
        requested_input_tokens: int,
        requested_output_tokens: int,
    ) -> float:
        wait_time = 0.0

        if self._cooldown_until > now:
            wait_time = max(wait_time, self._cooldown_until - now)

        if self._last_request_time > 0:
            elapsed = now - self._last_request_time
            interval_sec = self._request_interval_ms / 1000.0
            if elapsed < interval_sec:
                wait_time = max(wait_time, interval_sec - elapsed)

        if requested_input_tokens > 0 and self._input_token_allowance < requested_input_tokens:
            tokens_needed = requested_input_tokens - self._input_token_allowance
            wait_time = max(
                wait_time,
                tokens_needed / self._input_token_refill_rate / 1000.0,
            )

        if requested_output_tokens > 0 and self._output_token_allowance < requested_output_tokens:
            tokens_needed = requested_output_tokens - self._output_token_allowance
            wait_time = max(
                wait_time,
                tokens_needed / self._output_token_refill_rate / 1000.0,
            )

        return max(0.0, wait_time)

    def _claim_reservation(
        self,
        *,
        now: float,
        reservation_key: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
    ) -> ReservationTicket:
        ticket = ReservationTicket(
            ticket_id=self._next_ticket_id,
            reservation_key=reservation_key,
            reserved_input_tokens=reserved_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            acquired_at=now,
        )
        self._next_ticket_id += 1

        self._last_request_time = now
        self._request_count += 1
        self._cumulative_request_count += 1
        self._input_token_allowance -= reserved_input_tokens
        self._output_token_allowance -= reserved_output_tokens
        self._cumulative_reserved_input_tokens += reserved_input_tokens
        self._cumulative_reserved_output_tokens += reserved_output_tokens
        self._inflight_reserved_input_tokens += reserved_input_tokens
        self._inflight_reserved_output_tokens += reserved_output_tokens
        self._inflight[ticket.ticket_id] = ticket

        self._update_peak_utilization()
        return ticket

    def _refresh_window(self, now: float) -> None:
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._request_count = 0
            self._input_token_count = 0
            self._output_token_count = 0

    def _refill_tokens(self, now: float) -> None:
        elapsed_ms = (now - self._last_refill_time) * 1000.0
        if elapsed_ms <= 0:
            return

        self._input_token_allowance = min(
            float(self._config.input_tokens_per_minute),
            self._input_token_allowance + elapsed_ms * self._input_token_refill_rate,
        )
        self._output_token_allowance = min(
            float(self._config.output_tokens_per_minute),
            self._output_token_allowance + elapsed_ms * self._output_token_refill_rate,
        )
        self._last_refill_time = now

    def _select_output_reservation(
        self,
        reservation_key: str,
        explicit_output: int | None,
        max_output_tokens: int,
    ) -> int:
        if explicit_output is not None:
            return min(explicit_output, max_output_tokens)

        profile = self._profile_for(reservation_key)
        if profile.conservative_remaining > 0 or len(profile.output_history) < _OUTPUT_WARMUP_SAMPLES:
            return max_output_tokens

        history = sorted(profile.output_history)
        p90_index = max(0, math.ceil(len(history) * 0.90) - 1)
        p90_value = history[p90_index]
        avg_value = sum(history) / len(history)
        tuned = math.ceil(max(p90_value * 1.20, avg_value * 1.35, _MIN_OUTPUT_RESERVATION))
        return min(max_output_tokens, tuned)

    def _profile_for(self, reservation_key: str) -> ReservationProfile:
        return self._profiles.setdefault(reservation_key, ReservationProfile())

    def _pop_ticket(self, ticket: ReservationTicket) -> ReservationTicket:
        popped = self._inflight.pop(ticket.ticket_id, ticket)
        self._inflight_reserved_input_tokens = max(
            0,
            self._inflight_reserved_input_tokens - popped.reserved_input_tokens,
        )
        self._inflight_reserved_output_tokens = max(
            0,
            self._inflight_reserved_output_tokens - popped.reserved_output_tokens,
        )
        return popped

    def _refund_full(self, ticket: ReservationTicket) -> None:
        self._input_token_allowance = min(
            float(self._config.input_tokens_per_minute),
            self._input_token_allowance + ticket.reserved_input_tokens,
        )
        self._output_token_allowance = min(
            float(self._config.output_tokens_per_minute),
            self._output_token_allowance + ticket.reserved_output_tokens,
        )

    def _apply_actual_tokens(
        self,
        *,
        allowance: float,
        capacity: float,
        reserved_tokens: int,
        actual_tokens: int,
    ) -> float:
        delta = reserved_tokens - actual_tokens
        if delta >= 0:
            return min(capacity, allowance + delta)
        return allowance + delta

    def _build_stats(self, now: float) -> UsageStats:
        next_request_in_ms = 0.0
        if self._last_request_time > 0:
            elapsed_ms = (now - self._last_request_time) * 1000.0
            next_request_in_ms = max(0.0, self._request_interval_ms - elapsed_ms)
        if self._cooldown_until > now:
            next_request_in_ms = max(
                next_request_in_ms,
                (self._cooldown_until - now) * 1000.0,
            )

        return UsageStats(
            request_count=self._request_count,
            input_token_count=self._input_token_count,
            output_token_count=self._output_token_count,
            queue_size=self._queue_size,
            next_request_in_ms=next_request_in_ms,
            input_token_allowance=self._input_token_allowance,
            output_token_allowance=self._output_token_allowance,
            inflight_requests=len(self._inflight),
            inflight_reserved_input_tokens=self._inflight_reserved_input_tokens,
            inflight_reserved_output_tokens=self._inflight_reserved_output_tokens,
            input_headroom_pct=self._headroom_pct(
                self._input_token_allowance,
                float(self._config.input_tokens_per_minute),
            ),
            output_headroom_pct=self._headroom_pct(
                self._output_token_allowance,
                float(self._config.output_tokens_per_minute),
            ),
            peak_rpm_utilization_pct=self._peak_rpm_utilization_pct,
            peak_input_utilization_pct=self._peak_input_utilization_pct,
            peak_output_utilization_pct=self._peak_output_utilization_pct,
            cumulative_reserved_input_tokens=self._cumulative_reserved_input_tokens,
            cumulative_reserved_output_tokens=self._cumulative_reserved_output_tokens,
            cumulative_input_tokens=self._cumulative_input_tokens,
            cumulative_output_tokens=self._cumulative_output_tokens,
            rate_limit_retries=self._rate_limit_retries,
            under_reserved_count=self._under_reserved_count,
        )

    def _update_peak_utilization(self) -> None:
        rpm_utilization = (self._request_count / self._config.requests_per_minute) * 100.0
        input_utilization = self._utilization_pct(
            self._input_token_allowance,
            float(self._config.input_tokens_per_minute),
        )
        output_utilization = self._utilization_pct(
            self._output_token_allowance,
            float(self._config.output_tokens_per_minute),
        )
        self._peak_rpm_utilization_pct = max(self._peak_rpm_utilization_pct, rpm_utilization)
        self._peak_input_utilization_pct = max(
            self._peak_input_utilization_pct,
            input_utilization,
        )
        self._peak_output_utilization_pct = max(
            self._peak_output_utilization_pct,
            output_utilization,
        )

    @staticmethod
    def _headroom_pct(allowance: float, capacity: float) -> float:
        if capacity <= 0:
            return 0.0
        return max(0.0, min(100.0, (allowance / capacity) * 100.0))

    @staticmethod
    def _utilization_pct(allowance: float, capacity: float) -> float:
        if capacity <= 0:
            return 0.0
        return max(0.0, ((capacity - allowance) / capacity) * 100.0)

    @staticmethod
    def _format_tokens(tokens: int) -> str:
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        if tokens >= 1_000:
            return f"{tokens / 1_000:.1f}K"
        return str(tokens)
