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


@dataclass
class CompletionOptions:
    """Options for a completion request."""

    model: str
    max_tokens: int = 4096
    temperature: float = 0.0
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
