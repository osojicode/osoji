"""Provider-aware token counting utilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

from ..config import ANTHROPIC_MODEL_MEDIUM, DEFAULT_PROVIDER
from .registry import normalize_provider_name, qualify_model_name, strip_provider_prefix
from .types import Message, MessageRole


class TokenCounter:
    """Token counter with Anthropic exact counting and LiteLLM tokenizer fallback."""

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        default_model: str | None = None,
        client: AsyncAnthropic | None = None,
        litellm_token_counter: Callable[..., int] | None = None,
    ) -> None:
        self._provider = normalize_provider_name(provider)
        self._default_model = default_model
        self._client = client
        self._cache: dict[str, int] = {}
        self._litellm_token_counter = litellm_token_counter

    @property
    def label(self) -> str:
        if self._provider == DEFAULT_PROVIDER:
            return "Anthropic API"
        return "LiteLLM model-aware tokenizer"

    @property
    def cache_key_prefix(self) -> str:
        model = self._default_model or "unset"
        return f"{self._provider}:{model}:{self.label}"

    async def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic()
        return self._client

    def _resolved_model(self, model: str | None) -> str:
        resolved = model or self._default_model
        if resolved:
            return resolved
        if self._provider == DEFAULT_PROVIDER:
            return ANTHROPIC_MODEL_MEDIUM
        raise RuntimeError(
            f"No token-counting model configured for provider '{self._provider}'."
        )

    async def count_tokens_async(
        self,
        messages: list[Message],
        system: str | None = None,
        model: str | None = None,
    ) -> int:
        resolved_model = self._resolved_model(model)
        if self._provider == DEFAULT_PROVIDER:
            return await self._count_with_anthropic(messages, system, resolved_model)
        return await asyncio.to_thread(
            self._count_with_litellm,
            messages,
            system,
            resolved_model,
        )

    async def _count_with_anthropic(
        self,
        messages: list[Message],
        system: str | None,
        model: str,
    ) -> int:
        client = await self._get_client()
        api_messages = [
            {
                "role": msg.role.value if isinstance(msg.role, MessageRole) else msg.role,
                "content": msg.content,
            }
            for msg in messages
        ]
        kwargs: dict[str, Any] = {
            "model": strip_provider_prefix(self._provider, model),
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        response = await client.messages.count_tokens(**kwargs)
        return int(response.input_tokens)

    def _count_with_litellm(
        self,
        messages: list[Message],
        system: str | None,
        model: str,
    ) -> int:
        token_counter = self._litellm_token_counter
        if token_counter is None:
            from litellm import token_counter as litellm_token_counter

            token_counter = litellm_token_counter
            self._litellm_token_counter = token_counter

        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role)
            api_messages.append({"role": role, "content": msg.content})

        return int(
            token_counter(
                model=qualify_model_name(self._provider, model),
                messages=api_messages,
            )
        )

    async def count_text_async(
        self,
        text: str,
        *,
        model: str | None = None,
    ) -> int:
        resolved_model = self._resolved_model(model)
        cache_key = f"{self.cache_key_prefix}:{resolved_model}:{hash(text)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        messages = [Message(role=MessageRole.USER, content=text)]
        count = await self.count_tokens_async(messages, model=resolved_model)

        if len(self._cache) < 10_000:
            self._cache[cache_key] = count

        return count

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def estimate_tokens_offline(text: str) -> int:
    """Estimate tokens without provider-specific counting."""

    return len(text) // 4
