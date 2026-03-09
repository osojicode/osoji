"""OpenRouter provider compatibility wrapper backed by LiteLLM."""

from .litellm_provider import LiteLLMProvider


class OpenRouterProvider(LiteLLMProvider):
    """OpenRouter provider using the shared LiteLLM adapter."""

    def __init__(self) -> None:
        super().__init__("openrouter")
