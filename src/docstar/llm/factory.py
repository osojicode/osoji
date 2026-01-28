"""Factory function for creating LLM providers."""

from .base import LLMProvider
from .anthropic import AnthropicProvider


def create_provider(name: str = "anthropic") -> LLMProvider:
    """Create an LLM provider by name.

    Args:
        name: Provider name (currently only "anthropic" is supported)

    Returns:
        An LLMProvider instance

    Raises:
        ValueError: If the provider name is unknown
    """
    if name == "anthropic":
        return AnthropicProvider()

    raise ValueError(
        f"Unknown provider: {name}. "
        f"Valid providers: anthropic"
    )
