# src\osoji\llm\_provider_base.py
@source-hash: 63c68c8c795d6cdf
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:13Z

## Purpose
Shared abstract base class (`DirectProvider`) for LLM provider implementations that call vendor SDKs directly (bypassing litellm). Provides a complete retry/validation loop for tool calls, JSONL interaction logging, token budget enforcement, and unified Anthropic/OpenAI response parsing.

## Key Symbols

### `_ParsedResponse` (L35–42) — internal dataclass
Normalized SDK response container used between parse and retry layers. Fields: `result: CompletionResult`, `assistant_message: dict | None`, `response_format: str` ("anthropic" or "openai"), `response_headers: dict | None`.

### `_disable_wmi_if_needed()` (L45–64) — module-level utility
Windows-only workaround: sets `platform._wmi = None` to prevent Python 3.13 WMI COM deadlocks in long-running processes. Invoked once in `DirectProvider.__init__`.

### `DirectProvider` (L67–621) — abstract base class, extends `LLMProvider`
Abstract base requiring subclasses to implement:
- `_call_api(**kwargs)` (L79–81): raw async SDK call
- `_build_request_kwargs(messages, system, options)` (L84–95): build full kwargs dict; must include `'messages'` key as `list[dict]`
- `_parse_sdk_response(response)` (L97–100): parse SDK response into `_ParsedResponse`

#### Constructor (L70–76)
Calls `_disable_wmi_if_needed()`, initializes interaction log state, reads `OSOJI_LLM_LOG_PATH` env var.

#### `complete(messages, system, options)` (L122–213) — core public API
Full async completion with retry loop:
1. Builds request kwargs and enforces input token budget
2. If no required tool (`tool_choice.type != "tool"`): returns immediately after first response
3. Otherwise: loops up to `_MAX_TOOL_VALIDATION_ATTEMPTS` (3) times:
   - If required tool not called → `_build_missing_tool_retry_messages` + retry
   - If required tool present but schema invalid → `_build_retry_messages` with error feedback + retry
   - If required tool present and valid → returns accumulated token counts
4. Raises `RequiredToolCallError` or `ToolSchemaValidationError` on exhaustion

#### `set_interaction_log_path(path)` (L105–112)
Enables/disables JSONL interaction logging. Creates parent dirs automatically.

#### `llm_timeout` property (L115–116)
Returns `int(OSOJI_LLM_TIMEOUT env var)` or `_DEFAULT_LLM_TIMEOUT` (600s).

#### `_request_and_parse(request_kwargs, attempt)` (L219–232)
Calls `_call_api` then `_parse_sdk_response`; logs both success and error via `_log_interaction`.

#### `_log_interaction(...)` (L234–285)
Appends JSONL entry to `_interaction_log_path` with timestamp, sequence, provider name, attempt, request snapshot, and response/error data. Silently swallows `OSError` with a warning.

#### `_parse_anthropic_response(response)` (L291–331)
Parses Anthropic-format responses (content blocks of type "text" or "tool_use"). Sets `response_format="anthropic"`. Used by subclasses in `_parse_sdk_response`.

#### `_parse_openai_response(response)` (L333–378)
Parses OpenAI-format responses (choices[0].message with optional tool_calls). Sets `response_format="openai"`. Handles JSON-encoded `function.arguments`.

#### Tool Conversion Helpers (L384–413)
- `_convert_tools_anthropic(tools)`: maps `ToolDefinition` list to Anthropic `input_schema` format
- `_convert_tools_openai(tools)`: maps to OpenAI `function` wrapper format
- `_convert_tool_choice_openai(tool_choice)`: converts internal tool choice dict to OpenAI format (maps `type="tool"` → `{"type":"function","function":{"name":...}}`; `"auto"/"none"/"required"` → plain string)

#### Retry Helpers (L419–549)
- `_required_tool_name(options)`: extracts tool name only when `tool_choice.type == "tool"` (L419–424)
- `_has_required_tool_call(tool_calls, required)`: checks if named tool was called (L426–427)
- `_maybe_expand_missing_tool_max_tokens(...)` (L429–440): doubles `max_tokens` if `stop_reason == "length"` and not already expanded
- `_build_tool_feedback(tool_calls, schema_by_name, validators)` (L442–478): validates each tool call against JSON schema + custom validators; returns `(feedback_list, error_dict)`
- `_build_retry_messages(...)` (L480–512): constructs follow-up messages in Anthropic (`tool_result` blocks) or OpenAI (`role="tool"` messages) format
- `_build_missing_tool_retry_messages(...)` (L514–536): constructs user message prompting the model to call the missing tool; inserts token-limit hint when `stop_reason == "length"`
- `_messages_from_api_payload(messages)` (L538–549): converts raw API `list[dict]` back to `list[Message]` for token estimation
- `_enforce_input_token_budget(messages, system, options)` (L551–571): calls offline token estimator; raises `PromptTooLargeError` if over budget

#### Low-level Helpers (L577–621)
- `_normalize_openai_content(content)` (L577–591): handles `None`, `str`, `list` (with `text`/`output_text` part types), or fallback `str(content)`
- `_decode_tool_arguments(arguments)` (L593–604): decodes JSON string or dict; fallback keys `_raw_arguments` / `_value`
- `_stringify_arguments(arguments)` (L606–609): ensures arguments are a JSON string
- `_usage_value(response, primary_key, fallback_key)` (L611–616): reads token usage from response with primary/fallback key names
- `_field(obj, key, default)` (L618–621): unified attribute/dict accessor (supports both SDK objects and dicts)

## Constants
- `_MAX_TOOL_VALIDATION_ATTEMPTS = 3` (L29): max retry attempts for tool call validation
- `_DEFAULT_LLM_TIMEOUT = 600` (L30): default API timeout in seconds; overridden by `OSOJI_LLM_TIMEOUT` env var

## Architecture Notes
- Subclasses must implement three abstract methods; everything else (retry loop, logging, token budgets) is inherited.
- The retry loop accumulates `total_input_tokens` and `total_output_tokens` across all attempts (L133–134, L170–171, L211–212).
- `_build_request_kwargs` must include a `'messages'` key (as `list[dict]`) so the retry loop can update conversation history in-place on `retry_kwargs`.
- Both Anthropic and OpenAI wire formats are supported via the `response_format` discriminant in `_ParsedResponse`.
- Interaction log is append-only JSONL; sequence number is per-instance monotonic.
- `_field` abstraction allows parsing both dict responses and SDK dataclass responses uniformly.