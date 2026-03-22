"""Factory function for creating LLM providers."""

from .anthropic import AnthropicProvider
from .base import LLMProvider
from .claude_code import ClaudeCodeProvider
from .google import GoogleProvider
from .logging import LoggingProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .rate_limited import RateLimitedProvider
from .registry import normalize_provider_name
from .tokens import TokenCounter
from ..rate_limiter import RateLimiter

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "claude-code": ClaudeCodeProvider,
    "google": GoogleProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
}


def create_provider(name: str = "anthropic") -> LLMProvider:
    """Create an LLM provider by name."""

    normalized_name = normalize_provider_name(name)
    cls = _PROVIDERS.get(normalized_name)
    if cls is not None:
        return cls()

    valid = ", ".join(sorted(_PROVIDERS))
    raise ValueError(
        f"Unknown provider: {normalized_name}. "
        f"Valid providers: {valid}"
    )


def create_logging_provider(
    name: str = "anthropic",
    *,
    rate_limiter: RateLimiter | None = None,
    verbose: bool = False,
    default_model: str | None = None,
) -> LoggingProvider:
    """Create a provider wrapped with rate limiting and logging."""

    normalized_name = normalize_provider_name(name)
    provider: LLMProvider = create_provider(normalized_name)
    if rate_limiter is not None:
        provider = RateLimitedProvider(
            provider,
            rate_limiter,
            token_counter=TokenCounter(
                provider=normalized_name,
                default_model=default_model,
            ),
        )
    return LoggingProvider(provider, verbose=verbose)
