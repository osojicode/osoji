# src\osoji\llm\registry.py
@source-hash: 35c2df0af02fdeec
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:07Z

## Provider Registry and Model Normalization Helpers

Central registry for supported LLM providers and utilities for normalizing provider names and model name strings within the osoji LLM subsystem.

### Module-Level Constants

- **`DEFAULT_PROVIDER`** (L7): `"anthropic"` — fallback when no provider is specified.
- **`_KNOWN_PREFIXES`** (L11): Set of provider prefix strings that may appear in litellm-style model strings (e.g., `"openai/gpt-4"`). Used by stripping logic to produce bare model names for direct SDKs.
- **`_PROVIDER_SPECS`** (L25–61): Internal dict mapping provider name → `ProviderSpec`. Contains five entries: `"anthropic"`, `"openai"`, `"google"`, `"openrouter"`, `"claude-code"`.

### Key Class

**`ProviderSpec`** (L15–22) — frozen dataclass holding static metadata per provider:
- `name: str` — canonical key (matches dict key in `_PROVIDER_SPECS`)
- `display_name: str` — human-readable label
- `api_key_env: str` — environment variable name for the API key (empty string for `"claude-code"`)
- `rate_limit_name: str` — token used for rate-limiter lookup
- `requires_explicit_model: bool` — whether a model name must be explicitly provided (True for `"openai"` only)

### Public Functions

| Function | Lines | Purpose |
|---|---|---|
| `provider_names()` | L64–66 | Returns sorted tuple of all supported provider name strings |
| `normalize_provider_name(name)` | L69–75 | Strips/lowercases input, falls back to `DEFAULT_PROVIDER` if `None`/empty; raises `ValueError` with valid options on unknown provider |
| `get_provider_spec(name)` | L78–80 | Convenience wrapper: normalizes name then returns matching `ProviderSpec` |
| `qualify_model_name(provider, model)` | L83–89 | Delegates directly to `strip_provider_prefix`; strips litellm-style prefix from model string |
| `strip_provider_prefix(provider, model)` | L92–98 | Core stripping logic: if model contains `/` and the left part is a known prefix, returns only the right part; otherwise returns stripped model string |

### Architectural Notes

- `qualify_model_name` is a thin alias for `strip_provider_prefix`; both accept `provider` as a parameter but `provider` is **not used** in `strip_provider_prefix` — only the model string and the module-level `_KNOWN_PREFIXES` set drive the logic.
- Provider validation is centralized in `normalize_provider_name`; all other functions depend on it indirectly via `get_provider_spec`.
- `"claude-code"` has an empty `api_key_env`, indicating it uses CLI-based auth rather than an API key.
- The registry is purely static (no runtime mutation); `ProviderSpec` is frozen.