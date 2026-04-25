"""OpenAI provider using the openai SDK directly."""

from __future__ import annotations

import os
from typing import Any

import openai

from ._provider_base import DirectProvider, _ParsedResponse
from .registry import get_provider_spec
from .types import CompletionOptions, Message, MessageRole


class OpenAIProvider(DirectProvider):
    """OpenAI provider using the openai SDK."""

    _PROVIDER_NAME = "openai"

    def __init__(self) -> None:
        super().__init__()
        spec = get_provider_spec(self._PROVIDER_NAME)
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{spec.api_key_env} environment variable is not set. "
                f"Please set it to your {spec.display_name} API key."
            )
        self._client = self._make_client(api_key)

    def _make_client(self, api_key: str) -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(api_key=api_key)

    @property
    def name(self) -> str:
        return self._PROVIDER_NAME

    async def _call_api(self, **kwargs: Any) -> Any:
        return await self._client.chat.completions.create(**kwargs)

    def _build_request_kwargs(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> dict[str, Any]:
        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role)
            api_messages.append({"role": role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": options.model,
            "messages": api_messages,
            "max_tokens": options.max_tokens,
        }
        if options.temperature is not None:
            kwargs["temperature"] = options.temperature
        if options.tools:
            kwargs["tools"] = self._convert_tools_openai(options.tools)
        if options.tool_choice:
            kwargs["tool_choice"] = self._convert_tool_choice_openai(options.tool_choice)
        kwargs["timeout"] = self.llm_timeout
        return kwargs

    def _parse_sdk_response(self, response: Any) -> _ParsedResponse:
        return self._parse_openai_response(response)

    async def close(self) -> None:
        await self._client.close()
