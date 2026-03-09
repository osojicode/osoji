"""Anthropic provider compatibility wrapper backed by LiteLLM."""

import anthropic  # noqa: F401 - retained for compatibility with existing tests.

from .litellm_provider import LiteLLMProvider


class AnthropicProvider(LiteLLMProvider):
    """Anthropic Claude provider using the shared LiteLLM adapter."""

    def __init__(self) -> None:
        super().__init__("anthropic")
