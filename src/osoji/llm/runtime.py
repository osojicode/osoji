"""Shared runtime builder for provider-backed Osoji commands."""

from __future__ import annotations

from ..config import Config
from ..rate_limiter import RateLimiter, get_config_with_overrides
from .factory import create_provider
from .logging import LoggingProvider
from .rate_limited import RateLimitedProvider
from .tokens import TokenCounter


def create_runtime(
    config: Config,
    *,
    verbose: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> tuple[LoggingProvider, RateLimiter]:
    """Create a logging provider plus rate limiter from config."""

    provider = create_provider(config.provider or "anthropic")
    resolved_rate_limiter = (
        rate_limiter
        if rate_limiter is not None
        else RateLimiter(get_config_with_overrides(config.provider or "anthropic"))
    )
    token_counter = TokenCounter(
        provider=config.provider or "anthropic",
        default_model=config.model_for("medium"),
    )
    rate_limited_provider = RateLimitedProvider(
        provider,
        resolved_rate_limiter,
        token_counter=token_counter,
    )
    logging_provider = LoggingProvider(rate_limited_provider, verbose=verbose)
    return logging_provider, resolved_rate_limiter
