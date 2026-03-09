"""Tests for provider/model CLI options on LLM-backed commands."""

from click.testing import CliRunner

from osoji.cli import main


def test_shadow_help_shows_provider_and_model_options():
    runner = CliRunner()

    result = runner.invoke(main, ["shadow", "--help"])

    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output


def test_stats_help_shows_provider_and_model_options():
    runner = CliRunner()

    result = runner.invoke(main, ["stats", "--help"])

    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output


def test_audit_help_shows_provider_and_model_options():
    runner = CliRunner()

    result = runner.invoke(main, ["audit", "--help"])

    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output


def test_shadow_cli_flags_override_env(monkeypatch, tmp_path):
    runner = CliRunner()
    captured: dict[str, str] = {}

    monkeypatch.setenv("OSOJI_PROVIDER", "anthropic")
    monkeypatch.setenv("OSOJI_MODEL", "claude-sonnet-4-6")

    async def fake_generate_shadow_docs_async(config, verbose=False):
        captured["provider"] = config.provider
        captured["model"] = config.model_for("medium")
        return True

    monkeypatch.setattr("osoji.cli.generate_shadow_docs_async", fake_generate_shadow_docs_async)

    result = runner.invoke(
        main,
        [
            "shadow",
            str(tmp_path),
            "--provider",
            "openai",
            "--model",
            "gpt-4.1-mini",
        ],
    )

    assert result.exit_code == 0
    assert captured == {"provider": "openai", "model": "gpt-4.1-mini"}
