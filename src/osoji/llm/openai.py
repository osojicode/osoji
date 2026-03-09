"""OpenAI provider compatibility wrapper backed by LiteLLM."""

from .litellm_provider import LiteLLMProvider


class OpenAIProvider(LiteLLMProvider):
    """OpenAI provider using the shared LiteLLM adapter."""

    def __init__(self) -> None:
        super().__init__("openai")
