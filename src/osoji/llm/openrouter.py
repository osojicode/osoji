"""OpenRouter provider — openai SDK pointed at OpenRouter's API endpoint."""

from __future__ import annotations

import os

import openai

from .openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter provider using the openai SDK with OpenRouter base URL."""

    _PROVIDER_NAME = "openrouter"

    def _make_client(self, api_key: str) -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.environ.get("OSOJI_HTTP_REFERER", "https://osoji.ai"),
                "X-Title": os.environ.get("OSOJI_APP_TITLE", "osoji"),
            },
        )
