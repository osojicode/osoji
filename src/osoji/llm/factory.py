"""Factory function for creating LLM providers."""

from .anthropic import AnthropicProvider
from .base import LLMProvider
from .google import GoogleProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .registry import normalize_provider_name, provider_names

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
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

    valid = ", ".join(provider_names())
    raise ValueError(
        f"Unknown provider: {normalized_name}. "
        f"Valid providers: {valid}"
    )
