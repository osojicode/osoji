"""Type definitions for LLM provider abstraction."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(Enum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A message in a conversation."""

    role: MessageRole
    content: str


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
    tools: list[ToolDefinition] = field(default_factory=list)
    tool_choice: dict[str, str] | None = None


@dataclass
class CompletionResult:
    """Result from a completion request."""

    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str | None
