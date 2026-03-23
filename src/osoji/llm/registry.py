"""Provider registry and model normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PROVIDER = "anthropic"


@dataclass(frozen=True)
class ProviderSpec:
    """Static metadata for a supported LLM provider."""

    name: str
    display_name: str
    litellm_prefix: str
    api_key_env: str
    rate_limit_name: str
    requires_explicit_model: bool


_PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        display_name="Anthropic",
        litellm_prefix="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        rate_limit_name="anthropic",
        requires_explicit_model=False,
    ),
    "openai": ProviderSpec(
        name="openai",
        display_name="OpenAI",
        litellm_prefix="openai",
        api_key_env="OPENAI_API_KEY",
        rate_limit_name="openai",
        requires_explicit_model=True,
    ),
    "google": ProviderSpec(
        name="google",
        display_name="Google Gemini",
        litellm_prefix="gemini",
        api_key_env="GEMINI_API_KEY",
        rate_limit_name="google",
        requires_explicit_model=True,
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        display_name="OpenRouter",
        litellm_prefix="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        rate_limit_name="openrouter",
        requires_explicit_model=True,
    ),
    "claude-code": ProviderSpec(
        name="claude-code",
        display_name="Claude Code CLI",
        litellm_prefix="",
        api_key_env="",
        rate_limit_name="claude-code",
        requires_explicit_model=False,
    ),
}

_KNOWN_MODEL_PREFIXES = {
    spec.litellm_prefix for spec in _PROVIDER_SPECS.values() if spec.litellm_prefix
} | set(_PROVIDER_SPECS)


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
    """Add the LiteLLM provider prefix unless the model is already qualified."""

    spec = get_provider_spec(provider)
    stripped = model.strip()
    if "/" in stripped:
        prefix = stripped.split("/", 1)[0].lower()
        if prefix in _KNOWN_MODEL_PREFIXES:
            return stripped
    if not spec.litellm_prefix:
        return stripped
    return f"{spec.litellm_prefix}/{stripped}"


def strip_provider_prefix(provider: str, model: str) -> str:
    """Strip a provider prefix from a model string when present."""

    spec = get_provider_spec(provider)
    for prefix in (spec.litellm_prefix, spec.name):
        if model.startswith(f"{prefix}/"):
            return model[len(prefix) + 1 :]
    return model
