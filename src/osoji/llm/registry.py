"""Provider registry and model normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PROVIDER = "anthropic"

# Known provider prefixes a caller might include in a model string (e.g. "openai/gpt-4").
# These are stripped before passing the model name to a direct SDK.
_KNOWN_PREFIXES = {"anthropic", "openai", "gemini", "google", "openrouter", "claude-code"}


@dataclass(frozen=True)
class ProviderSpec:
    """Static metadata for a supported LLM provider."""

    name: str
    display_name: str
    api_key_env: str
    rate_limit_name: str
    requires_explicit_model: bool


_PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        display_name="Anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        rate_limit_name="anthropic",
        requires_explicit_model=False,
    ),
    "openai": ProviderSpec(
        name="openai",
        display_name="OpenAI",
        api_key_env="OPENAI_API_KEY",
        rate_limit_name="openai",
        requires_explicit_model=True,
    ),
    "google": ProviderSpec(
        name="google",
        display_name="Google Gemini",
        api_key_env="GEMINI_API_KEY",
        rate_limit_name="google",
        requires_explicit_model=False,
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        display_name="OpenRouter",
        api_key_env="OPENROUTER_API_KEY",
        rate_limit_name="openrouter",
        requires_explicit_model=False,
    ),
    "claude-code": ProviderSpec(
        name="claude-code",
        display_name="Claude Code CLI",
        api_key_env="",
        rate_limit_name="claude-code",
        requires_explicit_model=False,
    ),
}


def provider_names() -> tuple[str, ...]:
    """Return the supported provider names."""
    return tuple(sorted(_PROVIDER_SPECS))


def normalize_provider_name(name: str | None) -> str:
    """Normalize and validate a provider name."""
    normalized = (name or DEFAULT_PROVIDER).strip().lower()
    if normalized not in _PROVIDER_SPECS:
        valid = ", ".join(provider_names())
        raise ValueError(f"Unknown provider: {normalized}. Valid providers: {valid}")
    return normalized


def get_provider_spec(name: str | None) -> ProviderSpec:
    """Return metadata for a provider."""
    return _PROVIDER_SPECS[normalize_provider_name(name)]


def qualify_model_name(provider: str, model: str) -> str:
    """Strip any known provider prefix from a model name.

    Direct SDKs don't use litellm-style prefixes like 'openai/gpt-4'.
    This normalizes model strings that callers may have already qualified.
    """
    return strip_provider_prefix(provider, model)


def strip_provider_prefix(provider: str, model: str) -> str:
    """Strip a known provider prefix from a model string when present."""
    stripped = model.strip()
    if "/" in stripped:
        prefix = stripped.split("/", 1)[0].lower()
        if prefix in _KNOWN_PREFIXES:
            return stripped.split("/", 1)[1]
    return stripped
