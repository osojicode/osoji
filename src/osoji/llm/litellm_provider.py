"""Generic LiteLLM-backed provider implementation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import litellm

from .base import LLMProvider
from .registry import get_provider_spec, qualify_model_name
from .tokens import estimate_completion_input_tokens_offline
from .types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    PromptTooLargeError,
    RequiredToolCallError,
    ToolCall,
    ToolDefinition,
    ToolSchemaValidationError,
)
from .validate import validate_tool_input

_MAX_TOOL_VALIDATION_ATTEMPTS = 3

logger = logging.getLogger(__name__)


@dataclass
class _ParsedResponse:
    """Normalized response plus retry metadata."""

    result: CompletionResult
    assistant_message: dict[str, Any] | None
    response_format: str


class _LiteLLMMessagesProxy:
    """Proxy object exposing a `.messages.create()` surface for compatibility."""

    def __init__(self, create_fn: Callable[..., Awaitable[Any]]) -> None:
        self.create = create_fn


class _LiteLLMClientProxy:
    """Compatibility shim so tests can patch `_client.messages.create`."""

    def __init__(self, create_fn: Callable[..., Awaitable[Any]]) -> None:
        self.messages = _LiteLLMMessagesProxy(create_fn)

    async def close(self) -> None:
        return None


class LiteLLMProvider(LLMProvider):
    """Provider implementation that routes requests through LiteLLM."""

    def __init__(
        self,
        provider_name: str,
        *,
        acompletion_fn: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._spec = get_provider_spec(provider_name)
        api_key = os.environ.get(self._spec.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{self._spec.api_key_env} environment variable is not set. "
                f"Please set it to your {self._spec.display_name} API key."
        )
        self._acompletion = acompletion_fn or litellm.acompletion
        self._client = _LiteLLMClientProxy(self._create_completion)
        self._interaction_log_path: Path | None = None
        self._interaction_log_sequence = 0
        env_log_path = os.environ.get("OSOJI_LLM_LOG_PATH")
        if env_log_path:
            self.set_interaction_log_path(env_log_path)

    @property
    def name(self) -> str:
        return self._spec.name

    async def _create_completion(self, **kwargs: Any) -> Any:
        return await self._acompletion(**kwargs)

    def set_interaction_log_path(self, path: str | os.PathLike[str] | None) -> None:
        """Enable JSONL logging for each provider interaction."""

        if not path:
            self._interaction_log_path = None
            return
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._interaction_log_path = resolved

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        request_messages = self._convert_messages(messages, system)
        request_kwargs = self._build_request_kwargs(request_messages, options)
        self._enforce_input_token_budget(messages, system, options)
        current_max_tokens = options.max_tokens

        parsed = await self._request_and_parse(request_kwargs, attempt=1)
        total_input_tokens = parsed.result.input_tokens
        total_output_tokens = parsed.result.output_tokens

        required_tool_name = self._required_tool_name(options)
        if required_tool_name is None:
            return parsed.result

        schema_by_name = {tool.name: tool.input_schema for tool in options.tools}
        conversation_messages = request_messages
        attempts = 1

        while True:
            if not self._has_required_tool_call(parsed.result.tool_calls, required_tool_name):
                if attempts >= _MAX_TOOL_VALIDATION_ATTEMPTS:
                    raise RequiredToolCallError(
                        tool_name=required_tool_name,
                        attempts=attempts,
                        stop_reason=parsed.result.stop_reason,
                        observed_tool_names=[tool_call.name for tool_call in parsed.result.tool_calls],
                    )

                conversation_messages = self._build_missing_tool_retry_messages(
                    conversation_messages,
                    parsed.assistant_message,
                    required_tool_name,
                    parsed.result.stop_reason,
                )
                retry_messages = self._messages_from_api_payload(conversation_messages)
                self._enforce_input_token_budget(retry_messages, None, options)

                current_max_tokens = self._maybe_expand_missing_tool_max_tokens(
                    current_max_tokens=current_max_tokens,
                    base_max_tokens=options.max_tokens,
                    stop_reason=parsed.result.stop_reason,
                )
                retry_kwargs = dict(request_kwargs)
                retry_kwargs["messages"] = conversation_messages
                retry_kwargs["max_tokens"] = current_max_tokens
                parsed = await self._request_and_parse(
                    retry_kwargs,
                    attempt=attempts + 1,
                )
                total_input_tokens += parsed.result.input_tokens
                total_output_tokens += parsed.result.output_tokens
                attempts += 1
                continue

            tool_feedback, tool_errors = self._build_tool_feedback(
                parsed.result.tool_calls,
                schema_by_name,
                options.tool_input_validators,
            )
            if not tool_errors:
                return CompletionResult(
                    content=parsed.result.content,
                    tool_calls=parsed.result.tool_calls,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    model=parsed.result.model,
                    stop_reason=parsed.result.stop_reason,
                )

            if parsed.assistant_message is None or attempts >= _MAX_TOOL_VALIDATION_ATTEMPTS:
                raise ToolSchemaValidationError(
                    tool_errors=tool_errors,
                    attempts=attempts,
                )

            conversation_messages = self._build_retry_messages(
                conversation_messages,
                parsed.assistant_message,
                tool_feedback,
                parsed.response_format,
            )
            retry_messages = self._messages_from_api_payload(conversation_messages)
            self._enforce_input_token_budget(retry_messages, None, options)

            retry_kwargs = dict(request_kwargs)
            retry_kwargs["messages"] = conversation_messages
            retry_kwargs["max_tokens"] = current_max_tokens
            parsed = await self._request_and_parse(
                retry_kwargs,
                attempt=attempts + 1,
            )
            total_input_tokens += parsed.result.input_tokens
            total_output_tokens += parsed.result.output_tokens
            attempts += 1

    async def close(self) -> None:
        await self._client.close()

    def _build_request_kwargs(
        self,
        messages: list[dict[str, Any]],
        options: CompletionOptions,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": qualify_model_name(self.name, options.model),
            "messages": messages,
            "max_tokens": options.max_tokens,
        }
        if options.temperature is not None:
            kwargs["temperature"] = options.temperature
        if options.tools:
            kwargs["tools"] = self._convert_tools(options.tools)
        if options.tool_choice:
            kwargs["tool_choice"] = self._convert_tool_choice(options.tool_choice)
        return kwargs

    def _convert_messages(
        self,
        messages: list[Message],
        system: str | None,
    ) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role)
            api_messages.append({"role": role, "content": msg.content})
        return api_messages

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def _convert_tool_choice(self, tool_choice: dict[str, str]) -> dict[str, Any] | str:
        choice_type = tool_choice.get("type")
        if choice_type == "tool":
            return {
                "type": "function",
                "function": {"name": tool_choice["name"]},
            }
        if choice_type in {"auto", "none", "required"}:
            return choice_type
        return tool_choice

    def _should_validate_tool_calls(
        self,
        options: CompletionOptions,
        tool_calls: list[ToolCall],
    ) -> bool:
        return bool(
            options.tool_choice
            and options.tool_choice.get("type") == "tool"
            and tool_calls
            and options.tools
        )

    def _required_tool_name(self, options: CompletionOptions) -> str | None:
        if not options.tool_choice:
            return None
        if options.tool_choice.get("type") != "tool":
            return None
        return options.tool_choice.get("name")

    def _has_required_tool_call(
        self,
        tool_calls: list[ToolCall],
        required_tool_name: str,
    ) -> bool:
        return any(tool_call.name == required_tool_name for tool_call in tool_calls)

    def _maybe_expand_missing_tool_max_tokens(
        self,
        *,
        current_max_tokens: int,
        base_max_tokens: int,
        stop_reason: str | None,
    ) -> int:
        if stop_reason != "length":
            return current_max_tokens
        if current_max_tokens > base_max_tokens:
            return current_max_tokens
        return max(current_max_tokens, base_max_tokens * 2)

    def _build_tool_feedback(
        self,
        tool_calls: list[ToolCall],
        schema_by_name: dict[str, dict[str, Any]],
        validators: list[Callable[[str, dict], list[str]]],
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        tool_feedback: list[dict[str, Any]] = []
        tool_errors: dict[str, list[str]] = {}

        for tool_call in tool_calls:
            errors = self._validate_tool_call(tool_call, schema_by_name, validators)

            if errors:
                tool_errors.setdefault(tool_call.name, [])
                for error in errors:
                    if error not in tool_errors[tool_call.name]:
                        tool_errors[tool_call.name].append(error)
                feedback = {
                    "tool_use_id": tool_call.id,
                    "name": tool_call.name,
                    "content": (
                        "Schema validation errors - please re-call the tool "
                        "with corrected values:\n"
                        + "\n".join(f"- {error}" for error in errors)
                    ),
                    "is_error": True,
                }
            else:
                feedback = {
                    "tool_use_id": tool_call.id,
                    "name": tool_call.name,
                    "content": "OK",
                }
            tool_feedback.append(feedback)

        return tool_feedback, tool_errors

    def _build_retry_messages(
        self,
        request_messages: list[dict[str, Any]],
        assistant_message: dict[str, Any],
        tool_feedback: list[dict[str, Any]],
        response_format: str,
    ) -> list[dict[str, Any]]:
        retry_messages = list(request_messages)
        retry_messages.append(assistant_message)

        if response_format == "anthropic":
            retry_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": item["tool_use_id"],
                            "content": item["content"],
                            **({"is_error": True} if item.get("is_error") else {}),
                        }
                        for item in tool_feedback
                    ],
                }
            )
            return retry_messages

        for item in tool_feedback:
            retry_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["tool_use_id"],
                    "name": item["name"],
                    "content": item["content"],
                }
            )
        return retry_messages

    def _build_missing_tool_retry_messages(
        self,
        request_messages: list[dict[str, Any]],
        assistant_message: dict[str, Any] | None,
        tool_name: str,
        stop_reason: str | None,
    ) -> list[dict[str, Any]]:
        retry_messages = list(request_messages)
        if assistant_message is not None:
            retry_messages.append(assistant_message)

        reminder_lines = [
            f"You did not call the required tool `{tool_name}` in your previous response.",
            "Call that tool now.",
            "Do not answer with plain text.",
        ]
        if stop_reason == "length":
            reminder_lines.insert(
                1,
                "Your previous response hit the output token limit before the tool call.",
            )

        retry_messages.append(
            {
                "role": "user",
                "content": "\n".join(reminder_lines),
            }
        )
        return retry_messages

    def _validate_tool_call(
        self,
        tool_call: ToolCall,
        schema_by_name: dict[str, dict[str, Any]],
        validators: list[Callable[[str, dict], list[str]]],
    ) -> list[str]:
        errors: list[str] = []
        schema = schema_by_name.get(tool_call.name)
        if schema:
            errors.extend(validate_tool_input(tool_call.input, schema))
        for validator in validators:
            errors.extend(validator(tool_call.name, tool_call.input))
        return errors

    def _messages_from_api_payload(
        self,
        messages: list[dict[str, Any]],
    ) -> list[Message]:
        converted: list[Message] = []
        for message in messages:
            role = message.get("role", MessageRole.USER.value)
            converted.append(
                Message(
                    role=MessageRole(role) if role in MessageRole._value2member_map_ else role,
                    content=message.get("content", ""),
                )
            )
        return converted

    def _enforce_input_token_budget(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> None:
        if options.max_input_tokens is None:
            return

        estimated_tokens = estimate_completion_input_tokens_offline(
            messages,
            system=system,
            tools=options.tools,
            tool_choice=options.tool_choice,
        )
        if estimated_tokens > options.max_input_tokens:
            raise PromptTooLargeError(
                estimated_tokens=estimated_tokens,
                max_input_tokens=options.max_input_tokens,
                model=options.model,
                reservation_key=options.reservation_key,
            )

    async def _request_and_parse(
        self,
        request_kwargs: dict[str, Any],
        *,
        attempt: int,
    ) -> _ParsedResponse:
        try:
            response = await self._client.messages.create(**request_kwargs)
        except Exception as exc:
            self._log_interaction(
                request_kwargs=request_kwargs,
                attempt=attempt,
                error=exc,
            )
            raise

        parsed = self._parse_response(response)
        self._log_interaction(
            request_kwargs=request_kwargs,
            attempt=attempt,
            parsed=parsed,
        )
        return parsed

    def _log_interaction(
        self,
        *,
        request_kwargs: dict[str, Any],
        attempt: int,
        parsed: _ParsedResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        if self._interaction_log_path is None:
            return

        self._interaction_log_sequence += 1
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sequence": self._interaction_log_sequence,
            "provider": self.name,
            "attempt": attempt,
            "request": {
                "model": request_kwargs.get("model"),
                "messages": request_kwargs.get("messages"),
                "max_tokens": request_kwargs.get("max_tokens"),
                "temperature": request_kwargs.get("temperature"),
                "tools": request_kwargs.get("tools"),
                "tool_choice": request_kwargs.get("tool_choice"),
            },
        }

        if parsed is not None:
            entry["response"] = {
                "format": parsed.response_format,
                "assistant_message": parsed.assistant_message,
                "content": parsed.result.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.input,
                    }
                    for tool_call in parsed.result.tool_calls
                ],
                "input_tokens": parsed.result.input_tokens,
                "output_tokens": parsed.result.output_tokens,
                "model": parsed.result.model,
                "stop_reason": parsed.result.stop_reason,
            }

        if error is not None:
            entry["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }

        try:
            self._interaction_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._interaction_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")
        except OSError as exc:
            logger.warning(
                "Failed to write LLM interaction log to %s: %s",
                self._interaction_log_path,
                exc,
            )

    def _parse_response(self, response: Any) -> _ParsedResponse:
        if self._looks_like_anthropic_response(response):
            return self._parse_anthropic_response(response)
        return self._parse_openai_response(response)

    def _looks_like_anthropic_response(self, response: Any) -> bool:
        content = self._field(response, "content")
        return (
            isinstance(content, list)
            and bool(content)
            and self._field(content[0], "type") is not None
        )

    def _parse_anthropic_response(self, response: Any) -> _ParsedResponse:
        text_blocks: list[str] = []
        tool_calls: list[ToolCall] = []
        assistant_blocks: list[dict[str, Any]] = []

        for block in self._field(response, "content", []) or []:
            block_type = self._field(block, "type")
            if block_type == "text":
                text = self._field(block, "text", "")
                text_blocks.append(text)
                assistant_blocks.append({"type": "text", "text": text})
            elif block_type == "tool_use":
                tool_input = self._field(block, "input", {}) or {}
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": self._field(block, "id", ""),
                        "name": self._field(block, "name", ""),
                        "input": tool_input,
                    }
                )
                tool_calls.append(
                    ToolCall(
                        id=self._field(block, "id", ""),
                        name=self._field(block, "name", ""),
                        input=tool_input,
                    )
                )

        result = CompletionResult(
            content="".join(text_blocks) or None,
            tool_calls=tool_calls,
            input_tokens=self._usage_value(response, "input_tokens", "prompt_tokens"),
            output_tokens=self._usage_value(response, "output_tokens", "completion_tokens"),
            model=self._field(response, "model", ""),
            stop_reason=self._field(response, "stop_reason"),
        )
        assistant_message = (
            {"role": "assistant", "content": assistant_blocks} if assistant_blocks else None
        )
        return _ParsedResponse(
            result=result,
            assistant_message=assistant_message,
            response_format="anthropic",
        )

    def _parse_openai_response(self, response: Any) -> _ParsedResponse:
        choices = self._field(response, "choices", []) or []
        choice = choices[0] if choices else {}
        message = self._field(choice, "message", {}) or {}

        content = self._normalize_openai_content(self._field(message, "content"))
        tool_calls: list[ToolCall] = []
        assistant_tool_calls: list[dict[str, Any]] = []

        for raw_tool_call in self._field(message, "tool_calls", []) or []:
            function = self._field(raw_tool_call, "function", {}) or {}
            arguments = self._field(function, "arguments", "{}")
            tool_input = self._decode_tool_arguments(arguments)
            tool_calls.append(
                ToolCall(
                    id=self._field(raw_tool_call, "id", ""),
                    name=self._field(function, "name", ""),
                    input=tool_input,
                )
            )
            assistant_tool_calls.append(
                {
                    "id": self._field(raw_tool_call, "id", ""),
                    "type": self._field(raw_tool_call, "type", "function") or "function",
                    "function": {
                        "name": self._field(function, "name", ""),
                        "arguments": self._stringify_arguments(arguments),
                    },
                }
            )

        result = CompletionResult(
            content=content,
            tool_calls=tool_calls,
            input_tokens=self._usage_value(response, "prompt_tokens", "input_tokens"),
            output_tokens=self._usage_value(response, "completion_tokens", "output_tokens"),
            model=self._field(response, "model", ""),
            stop_reason=self._field(
                choice,
                "finish_reason",
                self._field(response, "stop_reason"),
            ),
        )

        assistant_message: dict[str, Any] | None = None
        if assistant_tool_calls or content is not None:
            assistant_message = {
                "role": "assistant",
                "content": content,
            }
            if assistant_tool_calls:
                assistant_message["tool_calls"] = assistant_tool_calls

        return _ParsedResponse(
            result=result,
            assistant_message=assistant_message,
            response_format="openai",
        )

    def _normalize_openai_content(self, content: Any) -> str | None:
        if content is None:
            return None
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                part_type = self._field(part, "type")
                if part_type in {None, "text", "output_text"}:
                    text = self._field(part, "text", self._field(part, "content", ""))
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts) or None
        return str(content)

    def _decode_tool_arguments(self, arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if arguments is None:
            return {}
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return {"_raw_arguments": arguments}
            if isinstance(parsed, dict):
                return parsed
            return {"_value": parsed}
        return {"_value": arguments}

    def _stringify_arguments(self, arguments: Any) -> str:
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments)

    def _usage_value(self, response: Any, primary_key: str, fallback_key: str) -> int:
        usage = self._field(response, "usage", {}) or {}
        value = self._field(usage, primary_key)
        if value is None:
            value = self._field(usage, fallback_key)
        return int(value or 0)

    def _field(self, obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
