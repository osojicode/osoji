"""Provider-aware prompt budgeting helpers."""

from __future__ import annotations

from ..config import Config

ANTHROPIC_MAX_INPUT_TOKENS = 150_000
DEFAULT_MAX_INPUT_TOKENS = 100_000


def input_budget_for_config(
    config: Config,
    *,
    anthropic_tokens: int = ANTHROPIC_MAX_INPUT_TOKENS,
    default_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
) -> int:
    """Return a conservative per-request input budget for the active provider."""

    provider = (config.provider or "").strip().lower()
    if provider == "anthropic":
        return anthropic_tokens
    return default_tokens
