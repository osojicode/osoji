"""Tests for provider and model resolution in Config."""

from pathlib import Path

import pytest

from osoji.config import (
    ANTHROPIC_MODEL_LARGE,
    ANTHROPIC_MODEL_MEDIUM,
    ANTHROPIC_MODEL_SMALL,
    Config,
)


def _clear_llm_env(monkeypatch):
    for name in (
        "OSOJI_PROVIDER",
        "OSOJI_MODEL",
        "OSOJI_MODEL_SMALL",
        "OSOJI_MODEL_MEDIUM",
        "OSOJI_MODEL_LARGE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_provider_defaults_to_anthropic(monkeypatch, tmp_path):
    _clear_llm_env(monkeypatch)

    config = Config(root_path=tmp_path)

    assert config.provider == "anthropic"
    assert config.model_for("small") == ANTHROPIC_MODEL_SMALL
    assert config.model_for("medium") == ANTHROPIC_MODEL_MEDIUM
    assert config.model_for("large") == ANTHROPIC_MODEL_LARGE


def test_env_provider_and_model_are_applied(monkeypatch, tmp_path):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OSOJI_PROVIDER", "openai")
    monkeypatch.setenv("OSOJI_MODEL", "gpt-4.1-mini")

    config = Config(root_path=tmp_path)

    assert config.provider == "openai"
    assert config.model_for("small") == "gpt-4.1-mini"
    assert config.model_for("medium") == "gpt-4.1-mini"


def test_constructor_values_override_env(monkeypatch, tmp_path):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OSOJI_PROVIDER", "anthropic")
    monkeypatch.setenv("OSOJI_MODEL", "claude-sonnet")

    config = Config(root_path=tmp_path, provider="google", model="gemini-2.0-flash")

    assert config.provider == "google"
    assert config.model_for("medium") == "gemini-2.0-flash"


def test_tier_override_wins_over_base_model(monkeypatch, tmp_path):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OSOJI_PROVIDER", "openrouter")
    monkeypatch.setenv("OSOJI_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("OSOJI_MODEL_SMALL", "meta-llama/llama-3.3-70b-instruct")

    config = Config(root_path=tmp_path)

    assert config.model_for("small") == "meta-llama/llama-3.3-70b-instruct"
    assert config.model_for("medium") == "openai/gpt-4.1-mini"


def test_non_anthropic_provider_requires_explicit_model(monkeypatch, tmp_path):
    _clear_llm_env(monkeypatch)

    config = Config(root_path=tmp_path, provider="openrouter")

    with pytest.raises(RuntimeError, match="Set --model, OSOJI_MODEL, or OSOJI_MODEL_MEDIUM"):
        config.model_for("medium")
