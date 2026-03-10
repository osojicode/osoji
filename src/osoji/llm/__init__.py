"""LLM provider abstraction package.

This package provides a unified interface for interacting with different
LLM providers.
"""

from .types import (
    MessageRole,
    Message,
    ToolDefinition,
    ToolCall,
    PromptTooLargeError,
    RequiredToolCallError,
    ToolSchemaValidationError,
    CompletionOptions,
    CompletionResult,
    RateLimitMetadata,
)
from .base import LLMProvider
from .anthropic import AnthropicProvider
from .google import GoogleProvider
from .logging import LoggingProvider, TokenStats
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .rate_limited import RateLimitedProvider
from .factory import create_provider, create_logging_provider
from .registry import get_provider_spec, normalize_provider_name, provider_names
from .runtime import create_runtime
from .tokens import TokenCounter, estimate_tokens_offline
from .validate import validate_tool_input

__all__ = [
    # Types
    "MessageRole",
    "Message",
    "ToolDefinition",
    "ToolCall",
    "PromptTooLargeError",
    "RequiredToolCallError",
    "ToolSchemaValidationError",
    "CompletionOptions",
    "CompletionResult",
    "RateLimitMetadata",
    # Providers
    "LLMProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "GoogleProvider",
    "OpenRouterProvider",
    "LoggingProvider",
    "RateLimitedProvider",
    "TokenStats",
    # Factory
    "create_provider",
    "create_logging_provider",
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
