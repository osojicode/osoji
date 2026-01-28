"""Anthropic LLM provider implementation."""

import os
from typing import Any

import anthropic

from .base import LLMProvider
from .types import (
    Message,
    MessageRole,
    ToolDefinition,
    ToolCall,
    CompletionOptions,
    CompletionResult,
)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider using async client."""

    def __init__(self) -> None:
        """Initialize the Anthropic provider.

        Raises:
            RuntimeError: If ANTHROPIC_API_KEY is not set
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Please set it to your Anthropic API key."
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "anthropic"

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        """Generate a completion using the Anthropic API.

        Args:
            messages: List of conversation messages
            system: Optional system prompt
            options: Completion options

        Returns:
            CompletionResult with content, tool calls, and usage
        """
        # Convert messages to Anthropic format
        api_messages = self._convert_messages(messages)

        # Convert tools to Anthropic format
        api_tools = self._convert_tools(options.tools) if options.tools else None

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": options.model,
            "max_tokens": options.max_tokens,
            "messages": api_messages,
        }

        if system:
            kwargs["system"] = system

        if options.temperature != 0.0:
            kwargs["temperature"] = options.temperature

        if api_tools:
            kwargs["tools"] = api_tools

        if options.tool_choice:
            kwargs["tool_choice"] = options.tool_choice

        # Make the API call
        response = await self._client.messages.create(**kwargs)

        # Extract results
        content = None
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    )
                )

        return CompletionResult(
            content=content,
            tool_calls=tool_calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
        )

    async def close(self) -> None:
        """Close the async client."""
        await self._client.close()

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        """Convert internal messages to Anthropic API format."""
        return [
            {
                "role": self._convert_role(msg.role),
                "content": msg.content,
            }
            for msg in messages
        ]

    def _convert_role(self, role: MessageRole) -> str:
        """Convert internal role to Anthropic API role."""
        role_map = {
            MessageRole.USER: "user",
            MessageRole.ASSISTANT: "assistant",
        }
        return role_map.get(role, "user")

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert internal tool definitions to Anthropic API format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
