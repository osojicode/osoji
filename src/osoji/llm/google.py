"""Google Gemini provider compatibility wrapper backed by LiteLLM."""

from .litellm_provider import LiteLLMProvider


class GoogleProvider(LiteLLMProvider):
    """Google Gemini provider using the shared LiteLLM adapter."""

    def __init__(self) -> None:
        super().__init__("google")
