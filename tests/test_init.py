"""Tests for osoji init module."""

from pathlib import Path

from osoji.init import merge_gitignore


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
