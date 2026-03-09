"""LLM provider abstraction package.

This package provides a unified interface for interacting with different
LLM providers.
"""

from .anthropic import AnthropicProvider
from .base import LLMProvider
from .factory import create_provider
from .google import GoogleProvider
from .logging import LoggingProvider, TokenStats
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .registry import get_provider_spec, normalize_provider_name, provider_names
from .runtime import create_runtime
from .tokens import TokenCounter, estimate_tokens_offline
from .types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
)
from .validate import validate_tool_input

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
    "OpenAIProvider",
    "GoogleProvider",
    "OpenRouterProvider",
    "LoggingProvider",
    "TokenStats",
    # Factory
    "create_provider",
    "create_runtime",
    "normalize_provider_name",
    "provider_names",
    "get_provider_spec",
    # Token counting
    "TokenCounter",
    "estimate_tokens_offline",
    # Validation
    "validate_tool_input",
]
