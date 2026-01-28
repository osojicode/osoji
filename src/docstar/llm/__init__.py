"""LLM provider abstraction package.

This package provides a unified interface for interacting with different
LLM providers (currently Anthropic Claude).
"""

from .types import (
    MessageRole,
    Message,
    ToolDefinition,
    ToolCall,
    CompletionOptions,
    CompletionResult,
)
from .base import LLMProvider
from .anthropic import AnthropicProvider
from .logging import LoggingProvider, TokenStats
from .factory import create_provider
from .tokens import TokenCounter, estimate_tokens_offline

__all__ = [
    # Types
    "MessageRole",
    "Message",
    "ToolDefinition",
    "ToolCall",
    "CompletionOptions",
    "CompletionResult",
    # Providers
    "LLMProvider",
    "AnthropicProvider",
    "LoggingProvider",
    "TokenStats",
    # Factory
    "create_provider",
    # Token counting
    "TokenCounter",
    "estimate_tokens_offline",
]
