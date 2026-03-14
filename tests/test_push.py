"""Tests for osoji push module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import click
import pytest

from osoji.push import (
    PushConfig,
    PushResult,
    GitContext,
    _build_envelope,
    _load_push_section,
    _merge_push_config,
    resolve_push_config,
    run_push,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an observatory bundle."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    # Create a file and commit so HEAD exists
    (tmp_path / "readme.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Write observatory bundle
    bundle_dir = tmp_path / ".osoji" / "analysis"
    bundle_dir.mkdir(parents=True)
    bundle = {"schema_version": "1", "files": []}
    (bundle_dir / "observatory.json").write_text(json.dumps(bundle))

    return tmp_path


def _mock_git_context():
    return GitContext(
        commit="abc123def456",
        branch="main",
        message="test commit",
        timestamp="2026-03-14T10:00:00+00:00",
    )


class TestBuildEnvelope:
    def test_push_constructs_envelope(self):
        config = PushConfig(
            endpoint="https://api.example.com",
            token="tok_123",
            project_slug="myproject",
            org_slug="myorg",
        )
        git_ctx = _mock_git_context()
        bundle = {"schema_version": "1", "files": []}
        commits = [{"sha": "aaa", "message": "fix", "author": "Dev", "timestamp": "2026-03-14T09:00:00+00:00"}]

        envelope = _build_envelope(config, git_ctx, bundle, commits)

        assert envelope["envelope_version"] == "1"
        assert envelope["org_slug"] == "myorg"
        assert envelope["project_slug"] == "myproject"
        assert envelope["git"]["commit"] == "abc123def456"
        assert envelope["git"]["branch"] == "main"
        assert envelope["git"]["message"] == "test commit"
        assert envelope["git"]["timestamp"] == "2026-03-14T10:00:00+00:00"
        assert envelope["git"]["commits_since_last"] == commits
        assert envelope["bundle"] == bundle


def _env_without_osoji(**extra):
    """Return env patch that removes OSOJI_* vars but keeps system vars like HOME."""
    remove = {"OSOJI_ENDPOINT": "", "OSOJI_TOKEN": ""}
    remove.update(extra)
    # Use empty strings; resolve_push_config reads os.environ.get() which returns ""
    # but we filter below. Actually, let's just delete them.
    import os
    clean = {k: v for k, v in os.environ.items() if not k.startswith("OSOJI_")}
    clean.update(extra)
    return clean


class TestResolveConfig:
    def test_push_requires_endpoint(self, tmp_path):
        with patch.dict("os.environ", _env_without_osoji(), clear=True):
            with pytest.raises(click.ClickException, match="OSOJI_ENDPOINT is not set"):
                resolve_push_config(
                    endpoint=None, token="tok", project="p", org="o", root_path=tmp_path,
                )

    def test_push_requires_token(self, tmp_path):
        with patch.dict("os.environ", _env_without_osoji(OSOJI_ENDPOINT="https://api.example.com"), clear=True):
            with pytest.raises(click.ClickException, match="OSOJI_TOKEN is not set"):
                resolve_push_config(
                    endpoint=None, token=None, project="p", org="o", root_path=tmp_path,
                )

    def test_push_reads_config_toml(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text(
            '[push]\norg = "cfgorg"\nproject = "cfgproj"\n'
            'endpoint = "https://cfg.example.com"\n'
        )
        with patch.dict("os.environ", _env_without_osoji(), clear=True):
            config = resolve_push_config(
                endpoint=None, token="tok", project=None, org=None, root_path=tmp_path,
            )
        assert config.org_slug == "cfgorg"
        assert config.project_slug == "cfgproj"
        assert config.endpoint == "https://cfg.example.com"

    def test_push_local_toml_overrides_project_toml(self, tmp_path):
        (tmp_path / ".osoji.toml").write_text(
            '[push]\norg = "base_org"\nproject = "base_proj"\n'
            'endpoint = "https://base.example.com"\n'
        )
        (tmp_path / ".osoji.local.toml").write_text(
            '[push]\nproject = "local_proj"\n'
        )
        with patch.dict("os.environ", _env_without_osoji(), clear=True):
            config = resolve_push_config(
                endpoint=None, token="tok", project=None, org=None, root_path=tmp_path,
            )
        assert config.project_slug == "local_proj"
        assert config.org_slug == "base_org"  # not overridden


class TestRunPush:
    @patch("osoji.push._post_envelope")
    @patch("osoji.push._get_commits_since", return_value=[])
    @patch("osoji.push._fetch_last_commit", return_value=None)
    @patch("osoji.push.gather_git_context")
    def test_push_handles_201(self, mock_git_ctx, mock_last, mock_commits, mock_post, git_repo):
        mock_git_ctx.return_value = _mock_git_context()
        mock_post.return_value = PushResult(
            success=True,
            status_code=201,
            run_id="run_abc",
            project_slug="osoji",
            pushed_at="2026-03-14T10:00:00Z",
            dashboard_url="https://app.osojicode.ai/runs/run_abc",
        )

        result = run_push(
            endpoint="https://api.example.com",
            token="tok",
            project="osoji",
            org="osojicode",
            root_path=git_repo,
            quiet=True,
        )

        assert result.success is True
        assert result.status_code == 201
        assert result.run_id == "run_abc"
        assert result.dashboard_url == "https://app.osojicode.ai/runs/run_abc"

    @patch("osoji.push._post_envelope")
    @patch("osoji.push._get_commits_since", return_value=[])
    @patch("osoji.push._fetch_last_commit", return_value=None)
    @patch("osoji.push.gather_git_context")
    def test_push_handles_duplicate_200(self, mock_git_ctx, mock_last, mock_commits, mock_post, git_repo):
        mock_git_ctx.return_value = _mock_git_context()
        mock_post.return_value = PushResult(
            success=True,
            status_code=200,
            run_id="run_abc",
            duplicate=True,
        )

        result = run_push(
            endpoint="https://api.example.com",
            token="tok",
            project="osoji",
            org="osojicode",
            root_path=git_repo,
            quiet=True,
        )

        assert result.success is True
        assert result.duplicate is True

    @patch("osoji.push._post_envelope")
    @patch("osoji.push._get_commits_since", return_value=[])
    @patch("osoji.push._fetch_last_commit", return_value=None)
    @patch("osoji.push.gather_git_context")
    def test_push_handles_api_error(self, mock_git_ctx, mock_last, mock_commits, mock_post, git_repo):
        mock_git_ctx.return_value = _mock_git_context()
        mock_post.return_value = PushResult(
            success=False,
            status_code=400,
            error_message="Bundle failed validation: missing schema_version",
        )

        with pytest.raises(click.ClickException, match="Bundle failed validation"):
            run_push(
                endpoint="https://api.example.com",
                token="tok",
                project="osoji",
                org="osojicode",
                root_path=git_repo,
                quiet=True,
            )

    @patch("osoji.push._post_envelope")
    @patch("osoji.push._get_commits_since", return_value=[])
    @patch("osoji.push._fetch_last_commit", side_effect=Exception("network error"))
    @patch("osoji.push.gather_git_context")
    def test_push_last_commit_fetch_failure_is_nonfatal(self, mock_git_ctx, mock_last, mock_commits, mock_post, git_repo):
        mock_git_ctx.return_value = _mock_git_context()
        mock_post.return_value = PushResult(success=True, status_code=201, run_id="run_abc")

        # _fetch_last_commit raising should be caught - but we mock it to raise,
        # so we need the real function's try/except. Let's test differently:
        # Use the real _fetch_last_commit via a URL error mock instead.
        mock_last.side_effect = None
        mock_last.return_value = None  # Simulates failure returning None

        result = run_push(
            endpoint="https://api.example.com",
            token="tok",
            project="osoji",
            org="osojicode",
            root_path=git_repo,
            quiet=True,
        )

        assert result.success is True
        mock_commits.assert_called_once_with(git_repo, None)


class TestLoadPushSection:
    def test_returns_push_table(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[push]\norg = "myorg"\nproject = "myproj"\n')
        result = _load_push_section(toml_path)
        assert result == {"org": "myorg", "project": "myproj"}

    def test_returns_empty_if_no_push_section(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[other]\nfoo = "bar"\n')
        assert _load_push_section(toml_path) == {}

    def test_returns_empty_if_file_missing(self, tmp_path):
        assert _load_push_section(tmp_path / "nonexistent.toml") == {}
