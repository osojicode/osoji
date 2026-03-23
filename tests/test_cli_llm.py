"""Tests for provider/model CLI options on LLM-backed commands."""

import json

from click.testing import CliRunner

from osoji.cli import main
from osoji.config import LOCAL_CONFIG_FILENAME


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


def test_diff_help_shows_provider_and_model_options():
    runner = CliRunner()

    result = runner.invoke(main, ["diff", "--help"])

    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output


def test_root_help_shows_global_verbosity_flags():
    runner = CliRunner()

    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "--verbose" in result.output
    assert "--quiet" in result.output


def test_subcommand_help_no_longer_shows_verbose_flag():
    runner = CliRunner()

    result = runner.invoke(main, ["audit", "--help"])

    assert result.exit_code == 0
    assert "--verbose" not in result.output


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


def test_config_show_reports_project_override(monkeypatch, tmp_path):
    runner = CliRunner()
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    global_config = home_dir / ".config" / "osoji" / "config.toml"
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text(
        "\n".join(
            [
                'default_provider = "openai"',
                "",
                "[providers.openai]",
                'medium = "gpt-5.2"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / LOCAL_CONFIG_FILENAME).write_text(
        "\n".join(
            [
                'default_provider = "openai"',
                "",
                "[providers.openai]",
                'medium = "gpt-5.4"',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(main, ["config", "show", str(tmp_path)])

    assert result.exit_code == 0
    assert "providers.openai.medium" in result.output
    assert str(tmp_path / LOCAL_CONFIG_FILENAME) in result.output
    assert "gpt-5.4" in result.output


def test_diff_cli_flags_override_env(monkeypatch):
    runner = CliRunner()
    captured: dict[str, str] = {}

    monkeypatch.setenv("OSOJI_PROVIDER", "anthropic")
    monkeypatch.setenv("OSOJI_MODEL", "claude-sonnet-4-6")

    class _Report:
        changed_source = []
        changed_docs = []
        stale_shadows = []
        has_issues = False

    def fake_run_diff(config, base_ref):
        captured["provider"] = config.provider
        captured["model"] = config.model_for("medium")
        assert base_ref == "main"
        return _Report()

    monkeypatch.setattr("osoji.cli.run_diff", fake_run_diff)

    result = runner.invoke(
        main,
        [
            "diff",
            "main",
            "--provider",
            "openai",
            "--model",
            "gpt-4.1-mini",
        ],
    )

    assert result.exit_code == 0
    assert captured == {"provider": "openai", "model": "gpt-4.1-mini"}


def test_audit_json_includes_config_snapshot(tmp_path):
    runner = CliRunner()
    audit_json = {
        "passed": True,
        "errors": 0,
        "warnings": 0,
        "infos": 0,
        "issues": [],
        "config": {
            "resolution_order": ["cli", "env", "project", "global", "builtin"],
            "provider": {"value": "openai", "source": "project", "trace": []},
            "models": {
                "small": {"value": "gpt-5-mini", "source": "global", "trace": []},
                "medium": {"value": "gpt-5.2", "source": "project", "trace": []},
                "large": {"value": "gpt-5.4", "source": "project", "trace": []},
            },
        },
    }
    analysis_root = tmp_path / ".osoji" / "analysis"
    analysis_root.mkdir(parents=True, exist_ok=True)
    (analysis_root / "audit-result.json").write_text(
        json.dumps(audit_json, indent=2),
        encoding="utf-8",
    )

    result = runner.invoke(main, ["report", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["config"]["provider"]["value"] == "openai"
    assert payload["config"]["models"]["large"]["value"] == "gpt-5.4"
