"""Token counting using Anthropic's official API."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

from .types import Message, MessageRole


class TokenCounter:
    """Token counter using Anthropic's count_tokens API.

    Provides accurate token counting via the Anthropic API with LRU caching
    to reduce API calls for repeated content.

    Example:
        >>> counter = TokenCounter()
        >>> tokens = await counter.count_tokens_async(messages, system="...")
        >>> text_tokens = await counter.count_text_async("Hello world")
    """

    def __init__(self, client: AsyncAnthropic | None = None):
        """Initialize TokenCounter.

        Args:
            client: Optional AsyncAnthropic client. If not provided,
                    creates one from environment.
        """
        self._client = client
        self._cache: dict[str, int] = {}

    async def _get_client(self) -> AsyncAnthropic:
        """Get or create the Anthropic client."""
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic()
        return self._client

    async def count_tokens_async(
        self,
        messages: list[Message],
        system: str | None = None,
        model: str = "claude-sonnet-4-5-20250514",
    ) -> int:
        """Count tokens for messages using Anthropic API.

        Args:
            messages: List of Message objects
            system: Optional system prompt
            model: Model to count tokens for

        Returns:
            Number of input tokens
        """
        client = await self._get_client()

        # Convert to Anthropic message format
        api_messages = [
            {"role": msg.role.value if isinstance(msg.role, MessageRole) else msg.role,
             "content": msg.content}
            for msg in messages
        ]

        # Build request kwargs
        kwargs: dict = {
            "model": model,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        response = await client.messages.count_tokens(**kwargs)
        return response.input_tokens

    async def count_text_async(
        self,
        text: str,
        model: str = "claude-sonnet-4-5-20250514",
    ) -> int:
        """Count tokens for plain text using Anthropic API.

        Wraps the text in a user message for counting.

        Args:
            text: Text to count tokens for
            model: Model to count tokens for

        Returns:
            Number of tokens
        """
        # Check cache first
        cache_key = f"{model}:{hash(text)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        messages = [Message(role=MessageRole.USER, content=text)]
        count = await self.count_tokens_async(messages, model=model)

        # Cache the result (limit cache size)
        if len(self._cache) < 1000:
            self._cache[cache_key] = count

        return count

    def count_text_sync(
        self,
        text: str,
        model: str = "claude-sonnet-4-5-20250514",
    ) -> int:
        """Count tokens for plain text synchronously.

        Sync wrapper around count_text_async.

        Args:
            text: Text to count tokens for
            model: Model to count tokens for

        Returns:
            Number of tokens
        """
        return asyncio.run(self.count_text_async(text, model))

    async def close(self) -> None:
        """Close the underlying client connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None


def estimate_tokens_offline(text: str) -> int:
    """Estimate tokens without API call (character-based approximation).

    This is a rough fallback for edge cases where API access is not available.
    Accuracy: ~20-30% margin of error.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    # Rough approximation: ~4 chars per token for code/English
    return len(text) // 4
