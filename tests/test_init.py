"""Tests for osoji init module."""

from pathlib import Path
from unittest.mock import patch, call

from osoji.init import merge_dotenv, merge_gitignore, merge_project_toml, run_init


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


class TestRunInit:
    def test_non_interactive_creates_all_files(self, tmp_path):
        """Non-interactive mode creates files with commented-out placeholders."""
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        assert (tmp_path / ".gitignore").exists()
        assert (tmp_path / ".env").exists()
        env_content = (tmp_path / ".env").read_text()
        assert "# ANTHROPIC_API_KEY=" in env_content

    def test_non_interactive_respects_existing_env(self, tmp_path):
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-existing\n")
        run_init(root=tmp_path, interactive=False, provider="anthropic")
        env_content = (tmp_path / ".env").read_text()
        assert "sk-existing" in env_content

    @patch("click.confirm", return_value=True)
    @patch("click.prompt", side_effect=["sk-test-key", "", "myproject"])
    def test_interactive_prompts_for_values(self, mock_prompt, mock_confirm, tmp_path):
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        env_content = (tmp_path / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-test-key" in env_content
        toml_content = (tmp_path / ".osoji.toml").read_text()
        assert 'project = "myproject"' in toml_content

    @patch("click.prompt", return_value="")
    @patch("click.confirm", return_value=False)
    def test_interactive_skips_when_declined(self, mock_confirm, mock_prompt, tmp_path):
        """When user declines all prompts, no files are created."""
        run_init(root=tmp_path, interactive=True, provider="anthropic")
        assert not (tmp_path / ".gitignore").exists()
        assert not (tmp_path / ".env").exists()

    def test_non_interactive_openai_provider(self, tmp_path):
        run_init(root=tmp_path, interactive=False, provider="openai")
        env_content = (tmp_path / ".env").read_text()
        assert "# OPENAI_API_KEY=" in env_content
        assert "ANTHROPIC_API_KEY" not in env_content
