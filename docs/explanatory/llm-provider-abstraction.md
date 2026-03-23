# Understanding the LLM Provider Abstraction

Osoji needs to call multiple LLM providers -- Anthropic, OpenAI, Google Gemini, OpenRouter, and Claude Code CLI -- through a single interface. This document explains the architecture that makes that possible, why each design decision was made, and how the pieces assemble at runtime.

## Why an abstraction layer?

Osoji's core pipeline (shadow documentation, audits, junk detection) issues hundreds of LLM requests per run. If that pipeline were coupled to a single provider's SDK, switching providers would require rewriting every call site. Worse, cross-cutting concerns like rate limiting and token tracking would need to be duplicated for each SDK.

The abstraction layer solves this by defining a narrow contract that all providers implement. The pipeline code only depends on that contract, and the runtime assembles the concrete provider, rate limiter, and logger into a decorator stack. Adding a new provider means implementing three methods, not modifying the pipeline.

## The provider contract: `LLMProvider` ABC

The abstract base class in `llm/base.py` defines the interface that every provider must satisfy:

- `name` (property) -- a string identifying the provider (e.g., `"anthropic"`, `"openai"`)
- `complete(messages, system, options) -> CompletionResult` -- the core async method that sends a prompt and returns a structured response
- `close()` -- connection and resource cleanup

The interface is intentionally minimal. Three abstract members are enough to model any request-response LLM interaction. The richness lives in the types that flow through these methods, not in the method count. This keeps the barrier to adding a new provider low while still supporting complex features like tool calling, token budgeting, and response metadata.

## The type system: `llm/types.py`

The types module defines the vocabulary shared by all providers and their callers:

**Conversation modeling:**
- `MessageRole` -- an enum with `SYSTEM`, `USER`, and `ASSISTANT` values
- `Message` -- a role plus content (string or structured content blocks)

**Tool-use protocol:**
- `ToolDefinition` -- a tool's `name`, `description`, and `input_schema` (JSON Schema dict)
- `ToolCall` -- a tool invocation with `id`, `name`, and parsed `input` dict

**Request configuration:**
- `CompletionOptions` -- everything the caller wants to control about a request: `model`, `max_tokens`, `temperature`, `tools`, `tool_choice`, `reservation_key` (for rate limiting), `estimated_input_tokens`, `reserved_output_tokens`, `max_input_tokens` (prompt budget), and `tool_input_validators` (custom validation callbacks)

**Response envelope:**
- `CompletionResult` -- the unified return type carrying `content`, `tool_calls`, `input_tokens`, `output_tokens`, `model`, `stop_reason`, optional `rate_limit` metadata, and `response_headers`
- `RateLimitMetadata` -- per-request reservation details including reserved vs. actual token counts, retry count, and headroom percentages

**Typed exceptions for recoverable failures:**
- `PromptTooLargeError` -- raised when estimated input tokens exceed the configured budget, carrying the estimated count, limit, model, and reservation key so the caller can decide how to truncate
- `RequiredToolCallError` -- raised when a forced tool call never appears after all retry attempts
- `ToolSchemaValidationError` -- raised when a tool call's output stays invalid after retry attempts

These types are the common currency of the entire LLM layer. Pipeline code constructs `CompletionOptions`, receives `CompletionResult`, and never needs to know which SDK produced the response.

## Concrete providers

### The LiteLLM universal adapter

The real implementation work lives in `LiteLLMProvider` (`llm/litellm_provider.py`). This class routes requests through the LiteLLM library, which supports dozens of LLM APIs through a unified interface. `LiteLLMProvider` handles:

- Message format conversion (Osoji's `Message` objects to API-specific dicts)
- Tool definition conversion (wrapping `ToolDefinition` in the OpenAI function-calling format)
- Response parsing for both Anthropic-style (content blocks with `type` field) and OpenAI-style (choices array with message) response formats
- Input token budget enforcement via `_enforce_input_token_budget`
- The self-correction loop for tool validation (up to 3 attempts with error feedback)
- JSONL interaction logging when `OSOJI_LLM_LOG_PATH` is set
- A Windows-specific workaround (`_disable_wmi_if_needed`) to prevent Python 3.13 WMI deadlocks

### Named provider wrappers

Each supported provider has a thin wrapper class. Four subclass `LiteLLMProvider`:

- `AnthropicProvider` (`llm/anthropic.py`) -- `LiteLLMProvider("anthropic")`
- `OpenAIProvider` (`llm/openai.py`) -- `LiteLLMProvider("openai")`
- `GoogleProvider` (`llm/google.py`) -- `LiteLLMProvider("google")`
- `OpenRouterProvider` (`llm/openrouter.py`) -- `LiteLLMProvider("openrouter")`

These wrappers exist so the factory and registry can instantiate providers by name without the caller needing to know the LiteLLM constructor argument. They are each about five lines of code.

The fifth provider subclasses `LLMProvider` directly rather than `LiteLLMProvider`:

- `ClaudeCodeProvider` (`llm/claude_code.py`) -- routes requests through the Claude Code CLI instead of LiteLLM, enabling use of Claude Code's own authentication and model routing

### The trade-off: native SDK vs. universal adapter

Early in development, each provider had a separate implementation using its native SDK. The current design consolidates all provider logic into `LiteLLMProvider`, with the named wrappers existing only for API key validation and naming. This approach favors broader model coverage and reduced code duplication over SDK-specific optimizations. The `_parse_response` method in `LiteLLMProvider` dynamically detects whether a response is in Anthropic or OpenAI format and dispatches accordingly, so the same code path handles all providers.

## The decorator pattern: composable middleware

Two decorator classes wrap any `LLMProvider` to add cross-cutting behavior without modifying the provider itself.

### `LoggingProvider` (`llm/logging.py`)

Wraps a provider and accumulates `TokenStats` across all requests:

- `total_input_tokens`, `total_output_tokens`, `request_count`
- `length_stop_count` and `length_stop_examples` -- tracks responses truncated by `max_tokens`
- In verbose mode, prints per-request token counts, reservation headroom, and retry counts
- `get_token_summary()` produces a human-readable report including rate limit statistics from the wrapped provider

### `RateLimitedProvider` (`llm/rate_limited.py`)

Wraps a provider with proactive reservation-based rate limiting. Before each request, it estimates input tokens, applies a safety multiplier, and acquires a `ReservationTicket` from the `RateLimiter`. After the request completes, it finalizes the reservation with actual usage. On retryable errors (LiteLLM `RateLimitError`, `APIConnectionError`, or API errors with HTTP status 500, 502, 503, 504, 529), it retries up to 3 times with exponential backoff capped at 30 seconds, or uses the server's `retry-after` header if present. It also auto-tunes rate limits from response headers on the first successful call.

For details on the reservation algorithm, see the [rate limiting and token budgeting](rate-limiting-and-token-budgeting.md) document.

### Why decorators instead of inheritance?

Decorators compose orthogonally. A `LoggingProvider` wrapping a `RateLimitedProvider` wrapping an `AnthropicProvider` gains both behaviors without either knowing about the other. Inheritance would force a rigid class hierarchy (`LoggingRateLimitedAnthropicProvider`?) that does not scale to new combinations. Mixins would work but introduce method resolution order complexity and make the wrapping order implicit rather than explicit.

## Provider registry and factory

### Registry: `llm/registry.py`

The registry maps provider names to `ProviderSpec` metadata:

- `ProviderSpec` is a frozen dataclass holding `name`, `display_name`, `litellm_prefix`, `api_key_env`, `rate_limit_name`, and `requires_explicit_model`
- `normalize_provider_name()` validates and lowercases provider strings
- `qualify_model_name()` prepends the LiteLLM provider prefix (e.g., `"anthropic/claude-sonnet-4-20250514"`) unless already qualified
- `strip_provider_prefix()` removes the prefix when passing model names to native SDKs

The registry is static data, not a service. It captures the invariant facts about each provider (API key environment variable, LiteLLM routing prefix) that the rest of the system needs.

### Factory: `llm/factory.py`

Two factory functions create providers:

- `create_provider(name)` -- looks up the provider class in `_PROVIDERS` dict and instantiates it
- `create_logging_provider(name, rate_limiter, verbose, default_model)` -- creates a provider, wraps it with `RateLimitedProvider` (if a rate limiter is provided), then wraps with `LoggingProvider`

### Runtime assembly: `llm/runtime.py`

The `create_runtime(config, verbose, rate_limiter)` function is the standard entry point used by audit, shadow generation, and junk analyzers. It:

1. Creates the bare provider via `create_provider(config.provider)`
2. Sets up interaction logging if configured
3. Creates or reuses a `RateLimiter` with provider-appropriate defaults
4. Creates a `TokenCounter` for accurate input token estimation
5. Wraps: bare provider -> `RateLimitedProvider` -> `LoggingProvider`
6. Returns `(LoggingProvider, RateLimiter)` so callers can access both the wrapped provider and the shared rate limiter

## Mental model: the request lifecycle

The following diagram shows the decorator stack and the flow of a single LLM request:

```
Caller (shadow.py, audit.py, deadcode.py, ...)
  |
  v
LoggingProvider.complete()       <-- starts timer
  |
  v
RateLimitedProvider.complete()   <-- estimates tokens, acquires reservation, waits if needed
  |
  v
LiteLLMProvider.complete()       <-- converts messages, calls LiteLLM, parses response
  |                                  validates tool output, retries on schema errors
  v
LiteLLM library                  <-- routes to Anthropic/OpenAI/Google/OpenRouter API
  |
  v
(HTTP response flows back up)
  |
  v
LiteLLMProvider                  <-- parses response format, extracts tool calls
  |
  v
RateLimitedProvider              <-- finalizes reservation with actual tokens,
  |                                  auto-tunes limits from headers,
  |                                  retries on rate-limit errors
  v
LoggingProvider                  <-- records token stats, warns on length stops
  |
  v
CompletionResult returned to caller
```

## Design trade-offs

**Why both named providers AND a universal LiteLLM adapter?** The named provider classes (`AnthropicProvider`, `OpenAIProvider`, etc.) exist for two reasons: they validate the correct API key at construction time, and they give the factory a clean name-to-class mapping. Under the hood, four of the five delegate to `LiteLLMProvider`. The exception is `ClaudeCodeProvider`, which subclasses `LLMProvider` directly and routes through the Claude Code CLI. This is a deliberate choice -- maintaining five separate SDK integrations would mean five times the parsing, error handling, and response normalization code, with no benefit to the user.

**Why async throughout?** Shadow documentation generation processes hundreds of files. Sequential LLM calls would be far too slow. The async design allows dozens of requests to be in flight simultaneously, bounded by the rate limiter. Even single-file operations like junk verification use async because they share the same `LLMProvider` interface, and forcing a sync variant would require duplicating the entire type system.

**Why `CompletionOptions` instead of keyword arguments?** Bundling request options into a dataclass provides type safety, makes it easy to pass options through the decorator chain without each decorator needing to know about every parameter, and allows callers to construct options incrementally (e.g., setting `reservation_key` for rate-limit tracking alongside `tools` for structured output).

**Relationship to the broader system.** The LLM provider layer is foundational -- virtually every significant operation in Osoji flows through it. Shadow generation, audit phases, junk analyzers, doc analysis, and obligation checking all construct `CompletionOptions`, call `complete()`, and process `CompletionResult`. Understanding this layer is a prerequisite for understanding any of those systems.
