"""Tests for osoji init module."""

import tomllib
from pathlib import Path
from unittest.mock import patch, call

from osoji.init import (
    _serialize_toml,
    merge_dotenv,
    merge_gitignore,
    merge_project_toml,
    merge_provider_toml,
    run_init,
)


class TestSerializeToml:
    def test_empty_dict(self):
        assert _serialize_toml({}) == ""

    def test_top_level_only(self):
        result = _serialize_toml({"default_provider": "anthropic"})
        parsed = tomllib.loads(result)
        assert parsed == {"default_provider": "anthropic"}

    def test_with_section(self):
        data = {"default_provider": "anthropic", "push": {"project": "osoji"}}
        result = _serialize_toml(data)
        parsed = tomllib.loads(result)
        assert parsed == data
        # default_provider must appear before [push]
        assert result.index("default_provider") < result.index("[push]")

    def test_with_nested_section(self):
        data = {"providers": {"openai": {"small": "gpt-5-mini", "large": "gpt-5.4"}}}
        result = _serialize_toml(data)
        parsed = tomllib.loads(result)
        assert parsed == data
        assert "[providers.openai]" in result

    def test_full_roundtrip(self):
        data = {
            "default_provider": "openai",
            "push": {"endpoint": "https://api.osojicode.ai", "project": "osoji"},
            "providers": {"openai": {"small": "gpt-5-mini", "large": "gpt-5.4"}},
        }
        result = _serialize_toml(data)
        parsed = tomllib.loads(result)
        assert parsed == data

    def test_string_escaping(self):
        data = {"key": 'value with "quotes" and \\backslash'}
        result = _serialize_toml(data)
        parsed = tomllib.loads(result)
        assert parsed == data


class TestMergeGitignore:
    def test_creates_gitignore_when_missing(self, tmp_path):
        actions = merge_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert ".osoji/" in content
        assert ".osoji.local.toml" in content
        assert ".env" in content
        assert len(actions) == 3
        assert all(a["action"] == "added" for a in actions)

    def test_skips_existing_entries(self, tmp_path):
        (tmp_path / ".gitignore").write_text(".osoji/\n.env\n")
        actions = merge_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert ".osoji.local.toml" in content
        added = [a for a in actions if a["action"] == "added"]
        skipped = [a for a in actions if a["action"] == "skipped"]
        assert len(added) == 1
        assert len(skipped) == 2

    def test_all_present_no_changes(self, tmp_path):
        (tmp_path / ".gitignore").write_text(".osoji/\n.osoji.local.toml\n.env\n")
        actions = merge_gitignore(tmp_path)
        assert all(a["action"] == "skipped" for a in actions)

    def test_appends_with_separator(self, tmp_path):
        (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc\n")
        actions = merge_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert "\n# Osoji\n" in content


class TestMergeDotenv:
    def test_creates_env_when_missing(self, tmp_path):
        values = {"ANTHROPIC_API_KEY": "sk-test", "OSOJI_TOKEN": ""}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-test" in content
        assert "# OSOJI_TOKEN=" in content
        added = [a for a in actions if a["action"] == "added"]
        assert len(added) == 2

    def test_skips_existing_keys(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-existing\n")
        values = {"ANTHROPIC_API_KEY": "sk-new", "OSOJI_TOKEN": "tok123"}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        assert "sk-existing" in content
        assert "sk-new" not in content
        assert "OSOJI_TOKEN=tok123" in content
        skipped = [a for a in actions if a["action"] == "skipped"]
        assert len(skipped) == 1
        assert skipped[0]["key"] == "ANTHROPIC_API_KEY"

    def test_empty_value_written_as_comment(self, tmp_path):
        values = {"OSOJI_TOKEN": ""}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        assert "# OSOJI_TOKEN=" in content

    def test_non_empty_value_written_bare(self, tmp_path):
        values = {"OSOJI_TOKEN": "tok123"}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        assert "OSOJI_TOKEN=tok123" in content
        assert "# OSOJI_TOKEN" not in content

    def test_handles_commented_existing_key(self, tmp_path):
        """A commented-out key (# OSOJI_TOKEN=) should NOT count as 'existing'."""
        (tmp_path / ".env").write_text("# OSOJI_TOKEN=\n")
        values = {"OSOJI_TOKEN": "tok123"}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        assert "OSOJI_TOKEN=tok123" in content
        added = [a for a in actions if a["action"] == "added"]
        assert len(added) == 1

    def test_skips_commented_placeholder_when_empty(self, tmp_path):
        """Writing an empty value when a commented-out placeholder exists should skip."""
        (tmp_path / ".env").write_text("# OSOJI_TOKEN=\n")
        values = {"OSOJI_TOKEN": ""}
        actions = merge_dotenv(tmp_path, values)
        content = (tmp_path / ".env").read_text()
        # Should NOT add a second placeholder
        assert content.count("OSOJI_TOKEN") == 1
        skipped = [a for a in actions if a["action"] == "skipped"]
        assert len(skipped) == 1


class TestMergeProjectToml:
    def test_creates_toml_when_missing(self, tmp_path):
        actions = merge_project_toml(tmp_path, project_slug="myproject")
        content = (tmp_path / ".osoji.toml").read_text()
        assert '[push]' in content
        assert 'project = "myproject"' in content
        assert len(actions) == 1
        assert actions[0]["action"] == "added"

    def test_skips_when_project_already_set(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text('[push]\nproject = "existing"\n')
        actions = merge_project_toml(tmp_path, project_slug="newproject")
        content = (tmp_path / ".osoji.toml").read_text()
        assert 'project = "existing"' in content
        assert "newproject" not in content
        assert actions[0]["action"] == "skipped"

    def test_adds_push_section_to_existing_toml(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text('default_provider = "openai"\n')
        actions = merge_project_toml(tmp_path, project_slug="myproject")
        content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "openai"' in content
        assert '[push]' in content
        assert 'project = "myproject"' in content
        assert actions[0]["action"] == "added"

    def test_no_project_slug_skips(self, tmp_path):
        actions = merge_project_toml(tmp_path, project_slug=None)
        assert not (tmp_path / ".osoji.toml").exists()
        assert actions[0]["action"] == "skipped"

    def test_project_with_preexisting_push_section(self, tmp_path):
        """Adding project to existing [push] must not create duplicate section."""
        (tmp_path / ".osoji.toml").write_text('[push]\nendpoint = "https://api.osojicode.ai"\n')
        actions = merge_project_toml(tmp_path, project_slug="osoji")
        content = (tmp_path / ".osoji.toml").read_text()
        parsed = tomllib.loads(content)  # must not raise
        assert parsed["push"]["project"] == "osoji"
        assert parsed["push"]["endpoint"] == "https://api.osojicode.ai"
        assert content.count("[push]") == 1
        assert actions[0]["action"] == "added"


class TestMergeProviderToml:
    def test_writes_provider_to_project_toml(self, tmp_path):
        actions = merge_provider_toml(tmp_path, provider="anthropic")
        content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "anthropic"' in content
        added = [a for a in actions if a["action"] == "added"]
        assert len(added) == 1
        assert added[0]["key"] == "default_provider"

    def test_writes_provider_to_local_toml(self, tmp_path):
        actions = merge_provider_toml(tmp_path, provider="openai", use_local=True)
        content = (tmp_path / ".osoji.local.toml").read_text()
        assert 'default_provider = "openai"' in content
        assert not (tmp_path / ".osoji.toml").exists()

    def test_writes_model_overrides(self, tmp_path):
        models = {"small": "custom-small", "large": "custom-large"}
        actions = merge_provider_toml(tmp_path, provider="openai", models=models)
        content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "openai"' in content
        assert "[providers.openai]" in content
        assert 'small = "custom-small"' in content
        assert 'large = "custom-large"' in content

    def test_skips_existing_provider(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text('default_provider = "anthropic"\n')
        actions = merge_provider_toml(tmp_path, provider="anthropic")
        skipped = [a for a in actions if a["action"] == "skipped"]
        assert len(skipped) == 1
        assert skipped[0]["key"] == "default_provider"

    def test_no_models_means_no_providers_section(self, tmp_path):
        actions = merge_provider_toml(tmp_path, provider="google")
        content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "google"' in content
        assert "[providers." not in content

    def test_merges_into_existing_toml(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text('[push]\nproject = "myproject"\n')
        actions = merge_provider_toml(tmp_path, provider="openai")
        content = (tmp_path / ".osoji.toml").read_text()
        assert '[push]' in content
        assert 'project = "myproject"' in content
        assert 'default_provider = "openai"' in content

    def test_provider_with_preexisting_push_section(self, tmp_path):
        """default_provider must be top-level, not inside [push]."""
        (tmp_path / ".osoji.toml").write_text('[push]\nendpoint = "https://api.osojicode.ai"\n')
        merge_provider_toml(tmp_path, provider="anthropic")
        content = (tmp_path / ".osoji.toml").read_text()
        parsed = tomllib.loads(content)
        # default_provider must be top-level, NOT inside push
        assert parsed.get("default_provider") == "anthropic"
        assert "default_provider" not in parsed.get("push", {})
        # endpoint must be preserved
        assert parsed["push"]["endpoint"] == "https://api.osojicode.ai"

    def test_provider_then_project_no_corruption(self, tmp_path):
        """Calling both merge functions in sequence produces valid TOML."""
        (tmp_path / ".osoji.toml").write_text('[push]\nendpoint = "https://api.osojicode.ai"\n')
        merge_provider_toml(tmp_path, provider="anthropic")
        merge_project_toml(tmp_path, project_slug="osoji")
        content = (tmp_path / ".osoji.toml").read_text()
        parsed = tomllib.loads(content)  # must not raise
        assert parsed["default_provider"] == "anthropic"
        assert parsed["push"]["endpoint"] == "https://api.osojicode.ai"
        assert parsed["push"]["project"] == "osoji"
        assert content.count("[push]") == 1


class TestRunInit:
    def test_non_interactive_creates_all_files(self, tmp_path):
        """Non-interactive mode creates files with commented-out placeholders."""
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        assert (tmp_path / ".gitignore").exists()
        assert (tmp_path / ".env").exists()
        env_content = (tmp_path / ".env").read_text()
        assert "# ANTHROPIC_API_KEY=" in env_content
        # Provider config is written to .osoji.toml
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "anthropic"' in toml_content

    def test_non_interactive_respects_existing_env(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-existing\n")
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        env_content = (tmp_path / ".env").read_text()
        assert "sk-existing" in env_content

    @patch("click.confirm", return_value=True)
    @patch("click.prompt")
    def test_interactive_prompts_for_values(self, mock_prompt, mock_confirm, tmp_path):
        # Prompts: provider selection (1), model accept (Y from confirm),
        # config target (1), API key, OSOJI_TOKEN, project slug
        mock_prompt.side_effect = [1, 1, "sk-test-key", "", "myproject"]
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        env_content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-test-key" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'project = "myproject"' in toml_content

    @patch("click.prompt", return_value="")
    @patch("click.confirm", return_value=False)
    def test_interactive_skips_when_declined(self, mock_confirm, mock_prompt, tmp_path):
        """When user declines all prompts, minimal files are created."""
        # confirm returns False for everything: gitignore (3x), model accept, API key, OSOJI_TOKEN
        # prompt calls: provider (1), small/medium/large models (defaults), config target (1), project slug
        from osoji.config import BUILTIN_PROVIDER_MODELS
        defaults = BUILTIN_PROVIDER_MODELS["anthropic"]
        mock_prompt.side_effect = [
            1,                    # provider selection
            defaults["small"],    # small model (confirm=False → override prompts)
            defaults["medium"],   # medium model
            defaults["large"],    # large model
            1,                    # config target
            "",                   # project slug
        ]
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        assert not (tmp_path / ".gitignore").exists()

    def test_non_interactive_openai_provider(self, tmp_path):
        run_init(root=tmp_path, interactive=False, provider="openai")
        env_content = (tmp_path / ".env").read_text()
        assert "# OPENAI_API_KEY=" in env_content
        assert "ANTHROPIC_API_KEY" not in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "openai"' in toml_content

    def test_non_interactive_claude_code_no_api_key(self, tmp_path):
        """claude-code provider has no API key env var — only OSOJI_TOKEN placeholder."""
        run_init(root=tmp_path, interactive=False, provider="claude-code")
        env_content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY" not in env_content
        assert "# OSOJI_TOKEN=" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "claude-code"' in toml_content

    def test_non_interactive_google_provider(self, tmp_path):
        run_init(root=tmp_path, interactive=False, provider="google")
        env_content = (tmp_path / ".env").read_text()
        assert "# GEMINI_API_KEY=" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "google"' in toml_content

    def test_non_interactive_openrouter_provider(self, tmp_path):
        run_init(root=tmp_path, interactive=False, provider="openrouter")
        env_content = (tmp_path / ".env").read_text()
        assert "# OPENROUTER_API_KEY=" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "openrouter"' in toml_content

    @patch("click.confirm", return_value=True)
    @patch("click.prompt")
    def test_interactive_provider_flag_skips_selection(self, mock_prompt, mock_confirm, tmp_path):
        """When --provider is explicitly set (not default), skip selection prompt."""
        # With provider="openai" (non-default), prompts are: model accept (confirm),
        # config target, API key, OSOJI_TOKEN, project slug
        mock_prompt.side_effect = [1, "sk-openai", "", "myproject"]
        run_init(root=tmp_path, interactive=True, provider="openai")
        env_content = (tmp_path / ".env").read_text()
        assert "OPENAI_API_KEY=sk-openai" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "openai"' in toml_content

    @patch("click.confirm")
    @patch("click.prompt")
    def test_interactive_model_override(self, mock_prompt, mock_confirm, tmp_path):
        """User can override individual model tiers."""
        # Sequence: provider (1=anthropic), model accept (N from confirm),
        # small model, medium model, large model, config target (1),
        # set API key? (Y), API key value, set OSOJI_TOKEN? (Y), token, project slug
        mock_confirm.side_effect = [
            True, True, True,  # gitignore entries
            False,             # decline model defaults
            True,              # set API key
            True,              # set OSOJI_TOKEN
        ]
        mock_prompt.side_effect = [
            1,                               # provider selection
            "my-small", "my-medium", "my-large",  # model overrides
            1,                               # config target
            "sk-key",                        # API key
            "",                              # OSOJI_TOKEN
            "myproject",                     # project slug
        ]
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "anthropic"' in toml_content
        assert "[providers.anthropic]" in toml_content
        assert 'small = "my-small"' in toml_content
        assert 'medium = "my-medium"' in toml_content
        assert 'large = "my-large"' in toml_content

    @patch("click.confirm", return_value=True)
    @patch("click.prompt")
    def test_interactive_local_config_target(self, mock_prompt, mock_confirm, tmp_path):
        """User can save provider config to .osoji.local.toml."""
        # provider (1), config target (2=local), API key, OSOJI_TOKEN, project slug
        mock_prompt.side_effect = [1, 2, "sk-key", "", "myproject"]
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        assert (tmp_path / ".osoji.local.toml").exists()
        local_content = (tmp_path / ".osoji.local.toml").read_text()
        assert 'default_provider = "anthropic"' in local_content

    @patch("click.confirm", return_value=True)
    @patch("click.prompt")
    def test_interactive_claude_code_skips_api_key(self, mock_prompt, mock_confirm, tmp_path):
        """claude-code provider skips API key prompt and model defaults."""
        # provider (5=claude-code), config target (1), OSOJI_TOKEN, project slug
        mock_prompt.side_effect = [5, 1, "", "myproject"]
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        # No API key in .env (only OSOJI_TOKEN placeholder if declined)
        if (tmp_path / ".env").exists():
            env_content = (tmp_path / ".env").read_text()
            assert "ANTHROPIC_API_KEY" not in env_content
            assert "OPENAI_API_KEY" not in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'default_provider = "claude-code"' in toml_content

    @patch("osoji.init._infer_project_from_git_remote", return_value="myproject")
    def test_non_interactive_idempotent(self, _mock_infer, tmp_path):
        """Running init twice is idempotent — skips existing entries."""
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        env_content = (tmp_path / ".env").read_text()
        assert env_content.count("ANTHROPIC_API_KEY") == 1
        assert env_content.count("OSOJI_TOKEN") == 1
        # TOML must be valid with no duplicate sections
        toml_content = (tmp_path / ".osoji.toml").read_text()
        parsed = tomllib.loads(toml_content)
        assert parsed.get("default_provider") == "anthropic"
        assert parsed["push"]["project"] == "myproject"
        assert toml_content.count("[push]") == 1

    @patch("osoji.init._infer_project_from_git_remote", return_value="osoji")
    def test_non_interactive_with_preexisting_push(self, _mock_infer, tmp_path):
        """Init on a repo with existing [push] endpoint preserves it and produces valid TOML."""
        (tmp_path / ".osoji.toml").write_text('[push]\nendpoint = "https://api.osojicode.ai"\n')
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        toml_content = (tmp_path / ".osoji.toml").read_text()
        parsed = tomllib.loads(toml_content)
        assert parsed["default_provider"] == "anthropic"
        assert parsed["push"]["endpoint"] == "https://api.osojicode.ai"
        assert parsed["push"]["project"] == "osoji"
        assert toml_content.count("[push]") == 1


class TestInitCLI:
    def test_init_non_interactive_creates_files(self, tmp_path):
        from click.testing import CliRunner
        from osoji.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--non-interactive"])
        assert result.exit_code == 0
        assert "Osoji project setup" in result.output
        assert "Provider setup" in result.output
        assert (tmp_path / ".gitignore").exists()
        assert (tmp_path / ".env").exists()

    def test_init_non_interactive_with_provider(self, tmp_path):
        from click.testing import CliRunner
        from osoji.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--non-interactive", "--provider", "google"])
        assert result.exit_code == 0
        assert "Google Gemini" in result.output
        env_content = (tmp_path / ".env").read_text()
        assert "GEMINI_API_KEY" in env_content

    def test_init_help(self):
        from click.testing import CliRunner
        from osoji.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "--non-interactive" in result.output
        assert "--provider" in result.output
