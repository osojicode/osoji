"""Type definitions for LLM provider abstraction."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class MessageRole(Enum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A message in a conversation."""

    role: MessageRole
    content: str | list[dict[str, Any]]


@dataclass
class ToolDefinition:
    """Definition of a tool that can be used by the LLM."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """A tool call made by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


class PromptTooLargeError(RuntimeError):
    """Raised when a request exceeds the configured local input-token budget."""

    def __init__(
        self,
        *,
        estimated_tokens: int,
        max_input_tokens: int,
        model: str,
        reservation_key: str,
    ) -> None:
        self.estimated_tokens = estimated_tokens
        self.max_input_tokens = max_input_tokens
        self.model = model
        self.reservation_key = reservation_key
        super().__init__(
            "Estimated prompt is too long: "
            f"{estimated_tokens} tokens > {max_input_tokens} maximum "
            f"for {reservation_key} ({model})"
        )


class ToolSchemaValidationError(RuntimeError):
    """Raised when a forced tool call stays invalid after all retry attempts."""

    def __init__(
        self,
        *,
        tool_errors: dict[str, list[str]],
        attempts: int,
    ) -> None:
        self.tool_errors = tool_errors
        self.attempts = attempts

        if len(tool_errors) == 1:
            tool_name, errors = next(iter(tool_errors.items()))
            details = "; ".join(errors)
            message = (
                f"Schema validation failed after {attempts} attempts for "
                f"{tool_name}: {details}"
            )
        else:
            parts = [
                f"{tool_name}: {'; '.join(errors)}"
                for tool_name, errors in sorted(tool_errors.items())
            ]
            message = (
                f"Schema validation failed after {attempts} attempts: "
                + " | ".join(parts)
            )

        super().__init__(message)


class RequiredToolCallError(RuntimeError):
    """Raised when a forced tool call never appears after all retry attempts."""

    def __init__(
        self,
        *,
        tool_name: str,
        attempts: int,
        stop_reason: str | None,
        observed_tool_names: list[str] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.attempts = attempts
        self.stop_reason = stop_reason
        self.observed_tool_names = observed_tool_names or []

        message = f"Required tool call '{tool_name}' missing after {attempts} attempts"
        if stop_reason == "length":
            message += " (response reached max_tokens before the tool call)"
        elif stop_reason:
            message += f" (last stop_reason={stop_reason})"
        if self.observed_tool_names:
            observed = ", ".join(sorted(set(self.observed_tool_names)))
            message += f"; observed tool calls: {observed}"

        super().__init__(message)


@dataclass
class CompletionOptions:
    """Options for a completion request."""

    model: str
    max_tokens: int = 4096
    max_input_tokens: int | None = None
    temperature: float | None = None  # None = omit; lets provider use its default
    reservation_key: str = "default"
    estimated_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    tools: list[ToolDefinition] = field(default_factory=list)
    tool_choice: dict[str, str] | None = None
    tool_input_validators: list[Callable[[str, dict], list[str]]] = field(default_factory=list)


@dataclass
class RateLimitMetadata:
    """Per-request reservation and headroom details."""

    reservation_key: str
    reserved_input_tokens: int
    reserved_output_tokens: int
    actual_input_tokens: int
    actual_output_tokens: int
    retry_count: int
    input_headroom_pct: float
    output_headroom_pct: float


@dataclass
class CompletionResult:
    """Result from a completion request."""

    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str | None
    rate_limit: RateLimitMetadata | None = None
