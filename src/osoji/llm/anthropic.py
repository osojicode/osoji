"""Anthropic provider using the anthropic SDK directly."""

from __future__ import annotations

import os
from typing import Any

import anthropic

from ._provider_base import DirectProvider, _ParsedResponse
from .registry import get_provider_spec
from .types import CompletionOptions, Message, MessageRole


class AnthropicProvider(DirectProvider):
    """Anthropic Claude provider using the anthropic SDK."""

    def __init__(self) -> None:
        super().__init__()
        spec = get_provider_spec("anthropic")
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{spec.api_key_env} environment variable is not set. "
                f"Please set it to your {spec.display_name} API key."
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    async def _call_api(self, **kwargs: Any) -> Any:
        return await self._client.messages.create(**kwargs)

    def _build_request_kwargs(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> dict[str, Any]:
        api_messages = [
            {
                "role": msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in messages
        ]
        kwargs: dict[str, Any] = {
            "model": options.model,
            "messages": api_messages,
            "max_tokens": options.max_tokens,
        }
        if system:
            # cache_control on the system prompt enables Anthropic's prompt caching.
            # The system prompt is stable across audit calls and benefits most from caching.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if options.temperature is not None:
            kwargs["temperature"] = options.temperature
        if options.tools:
            kwargs["tools"] = self._convert_tools_anthropic(options.tools)
        if options.tool_choice:
            tc = options.tool_choice
            if tc.get("type") == "tool":
                kwargs["tool_choice"] = {"type": "tool", "name": tc["name"]}
            elif tc.get("type") in {"auto", "any"}:
                kwargs["tool_choice"] = {"type": tc["type"]}
        kwargs["timeout"] = self.llm_timeout
        return kwargs

    def _parse_sdk_response(self, response: Any) -> _ParsedResponse:
        return self._parse_anthropic_response(response)

    async def close(self) -> None:
        await self._client.close()
