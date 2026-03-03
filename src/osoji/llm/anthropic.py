"""Anthropic LLM provider implementation."""

import logging
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
from .validate import validate_tool_input

logger = logging.getLogger(__name__)


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
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=300.0,
            max_retries=3,
        )

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

        result = CompletionResult(
            content=content,
            tool_calls=tool_calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
        )

        # --- Validate forced tool calls and retry once on schema errors ---
        if (
            options.tool_choice
            and options.tool_choice.get("type") == "tool"
            and tool_calls
            and options.tools
        ):
            schema_by_name = {t.name: t.input_schema for t in options.tools}
            tool_results: list[dict[str, Any]] = []
            has_errors = False

            for tc in tool_calls:
                tc_schema = schema_by_name.get(tc.name)
                if tc_schema:
                    errs = validate_tool_input(tc.input, tc_schema)
                else:
                    errs = []

                for validator in options.tool_input_validators:
                    errs.extend(validator(tc.name, tc.input))

                if errs:
                    has_errors = True
                    nudge = (
                        "Schema validation errors — please re-call the tool "
                        "with corrected values:\n" + "\n".join(f"- {e}" for e in errs)
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": nudge,
                            "is_error": True,
                        }
                    )
                else:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": "OK",
                        }
                    )

            if has_errors:
                # Build retry conversation
                assistant_blocks = list(response.content)
                retry_assistant = {
                    "role": "assistant",
                    "content": [
                        {
                            "type": b.type,
                            **({"text": b.text} if b.type == "text" else {}),
                            **(
                                {
                                    "id": b.id,
                                    "name": b.name,
                                    "input": b.input,
                                }
                                if b.type == "tool_use"
                                else {}
                            ),
                        }
                        for b in assistant_blocks
                    ],
                }
                retry_user = {"role": "user", "content": tool_results}

                retry_kwargs = dict(kwargs)
                retry_kwargs["messages"] = (
                    list(kwargs["messages"]) + [retry_assistant, retry_user]
                )

                retry_response = await self._client.messages.create(**retry_kwargs)

                # Extract retry results
                retry_content = None
                retry_tool_calls: list[ToolCall] = []
                for block in retry_response.content:
                    if block.type == "text":
                        retry_content = block.text
                    elif block.type == "tool_use":
                        retry_tool_calls.append(
                            ToolCall(
                                id=block.id,
                                name=block.name,
                                input=block.input,
                            )
                        )

                # Validate retry tool calls
                for tc in retry_tool_calls:
                    retry_errs: list[str] = []
                    tc_schema = schema_by_name.get(tc.name)
                    if tc_schema:
                        retry_errs = validate_tool_input(tc.input, tc_schema)
                    for validator in options.tool_input_validators:
                        retry_errs.extend(validator(tc.name, tc.input))
                    if retry_errs:
                        logger.warning(
                            "Schema errors persist after retry for %s: %s",
                            tc.name,
                            "; ".join(retry_errs),
                        )

                result = CompletionResult(
                    content=retry_content,
                    tool_calls=retry_tool_calls,
                    input_tokens=(
                        response.usage.input_tokens
                        + retry_response.usage.input_tokens
                    ),
                    output_tokens=(
                        response.usage.output_tokens
                        + retry_response.usage.output_tokens
                    ),
                    model=retry_response.model,
                    stop_reason=retry_response.stop_reason,
                )

        return result

    async def close(self) -> None:
        """Close the async client."""
        await self._client.close()

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
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
