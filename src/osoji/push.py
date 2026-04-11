"""Push observatory bundle to osoji-teams ingest API."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import click
import tomllib
from dotenv import dotenv_values

from . import __version__
from .config import LOCAL_CONFIG_FILENAME, PROJECT_CONFIG_FILENAME, get_global_config_path
from .hooks import find_git_root
from .observatory import write_observatory_bundle

_USER_AGENT = f"osoji/{__version__}"


@dataclass(frozen=True)
class PushConfig:
    """Resolved push configuration."""

    endpoint: str
    token: str
    project_slug: str
    token_source: str = ""  # provenance label for diagnostics


@dataclass(frozen=True)
class GitContext:
    """Git metadata for the current HEAD."""

    commit: str
    branch: str
    message: str
    timestamp: str


@dataclass(frozen=True)
class PushResult:
    """Result of a push operation."""

    success: bool
    status_code: int | None = None
    run_id: str | None = None
    project_slug: str | None = None
    pushed_at: str | None = None
    dashboard_url: str | None = None
    duplicate: bool = False
    error_message: str | None = None


def _load_push_section(path: Path) -> dict[str, str]:
    """Read a TOML file and return its [push] table, or {} if absent."""

    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    push = data.get("push")
    if not isinstance(push, dict):
        return {}
    return {k: str(v) for k, v in push.items() if isinstance(v, str)}


def _merge_push_config(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Merge [push] config and track which file each key came from."""

    merged: dict[str, str] = {}
    sources: dict[str, str] = {}
    for path, label in [
        (get_global_config_path(), "global config"),
        (root / PROJECT_CONFIG_FILENAME, ".osoji.toml"),
        (root / LOCAL_CONFIG_FILENAME, ".osoji.local.toml"),
    ]:
        section = _load_push_section(path)
        for k, v in section.items():
            merged[k] = v
            sources[k] = label
    return merged, sources


def _infer_project_from_git_remote(root: Path) -> str | None:
    """Infer project slug from the git remote origin URL (repo name)."""

    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None

    url = result.stdout.strip()
    if not url:
        return None

    # SSH: git@host:org/repo.git
    ssh_match = re.match(r"git@[^:]+:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(2)

    # HTTPS: https://host/org/repo.git
    https_match = re.match(r"https?://[^/]+/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(2)

    return None


def _classify_env_source(var_name: str) -> str:
    """Return '.env file' if the env var value matches the .env file, else 'env var'."""

    env_file = dotenv_values()
    env_val = os.environ.get(var_name)
    if env_val and var_name in env_file and env_file[var_name] == env_val:
        return ".env file"
    return f"{var_name} env var"


def resolve_push_config(
    *,
    endpoint: str | None,
    token: str | None,
    project: str | None,
    root_path: Path,
) -> PushConfig:
    """Resolve push config: CLI arg -> env var -> TOML config -> git remote -> error."""

    merged, toml_sources = _merge_push_config(root_path)

    # --- endpoint ---
    if endpoint:
        resolved_endpoint = endpoint
    elif os.environ.get("OSOJI_ENDPOINT"):
        resolved_endpoint = os.environ["OSOJI_ENDPOINT"]
    elif merged.get("endpoint"):
        resolved_endpoint = merged["endpoint"]
    else:
        raise click.ClickException(
            "OSOJI_ENDPOINT is not set. Set [push] endpoint in .osoji.toml, "
            "pass --endpoint, or set the OSOJI_ENDPOINT environment variable."
        )

    # --- token ---
    if token:
        resolved_token = token
        token_source = "--token flag"
    elif os.environ.get("OSOJI_TOKEN"):
        resolved_token = os.environ["OSOJI_TOKEN"]
        token_source = _classify_env_source("OSOJI_TOKEN")
    elif merged.get("token"):
        resolved_token = merged["token"]
        token_source = toml_sources["token"]
    else:
        raise click.ClickException(
            "OSOJI_TOKEN is not set. Add OSOJI_TOKEN=<your-token> to .env, "
            "or pass --token, or set the OSOJI_TOKEN environment variable."
        )

    # --- project ---
    resolved_project = project or merged.get("project")
    if not resolved_project:
        resolved_project = _infer_project_from_git_remote(root_path)

    if not resolved_project:
        raise click.ClickException(
            "Project slug could not be determined. Pass --project or set [push].project in .osoji.toml."
        )

    resolved_endpoint = resolved_endpoint.rstrip("/")
    if not resolved_endpoint.startswith(("http://", "https://")):
        resolved_endpoint = f"https://{resolved_endpoint}"

    return PushConfig(
        endpoint=resolved_endpoint,
        token=resolved_token,
        project_slug=resolved_project,
        token_source=token_source,
    )


def gather_git_context(root: Path) -> GitContext:
    """Collect git metadata for the current HEAD."""

    def _git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()

    return GitContext(
        commit=_git("rev-parse", "HEAD"),
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        message=_git("log", "-1", "--pretty=%s"),
        timestamp=_git("log", "-1", "--pretty=%cI"),
    )


def _fetch_last_commit(endpoint: str, project_slug: str, token: str) -> str | None:
    """GET the last-pushed commit SHA for a project. Returns None on 404."""

    url = f"{endpoint}/api/v1/projects/{project_slug}/last-commit"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", _USER_AGENT)

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("commit")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        click.echo(f"Warning: failed to fetch last commit (HTTP {exc.code}), continuing.", err=True)
        return None
    except (URLError, OSError, json.JSONDecodeError):
        click.echo("Warning: failed to fetch last commit, continuing.", err=True)
        return None


def _get_commits_since(root: Path, since_sha: str | None) -> list[dict[str, str]]:
    """Return commits between since_sha and HEAD."""

    if since_sha is None:
        return []

    try:
        result = subprocess.run(
            ["git", "log", f"{since_sha}..HEAD", "--pretty=%H%x00%s%x00%an%x00%cI"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\x00", 3)
        if len(parts) == 4:
            commits.append({
                "sha": parts[0],
                "message": parts[1],
                "author": parts[2],
                "timestamp": parts[3],
            })
    return commits


def _build_envelope(
    push_config: PushConfig,
    git_context: GitContext,
    bundle: dict,
    commits_since: list[dict[str, str]],
) -> dict:
    """Construct the ingest API envelope."""

    return {
        "envelope_version": "1",
        "project_slug": push_config.project_slug,
        "git": {
            "commit": git_context.commit,
            "branch": git_context.branch,
            "message": git_context.message,
            "timestamp": git_context.timestamp,
            "commits_since_last": commits_since,
        },
        "bundle": bundle,
    }


def _post_envelope(endpoint: str, token: str, envelope: dict) -> PushResult:
    """POST the envelope to the ingest API."""

    url = f"{endpoint}/api/v1/ingest"
    body = json.dumps(envelope).encode("utf-8")

    req = Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", _USER_AGENT)

    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            status = resp.status
            duplicate = status == 200
            return PushResult(
                success=True,
                status_code=status,
                run_id=data.get("run_id"),
                project_slug=data.get("project_slug"),
                pushed_at=data.get("pushed_at"),
                dashboard_url=data.get("dashboard_url"),
                duplicate=duplicate,
            )
    except HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode()
        except Exception:
            pass

        if exc.code == 401:
            return PushResult(
                success=False,
                status_code=401,
                error_message="Authentication failed. Check your OSOJI_TOKEN value.",
            )
        if exc.code == 413:
            return PushResult(
                success=False,
                status_code=413,
                error_message="Bundle too large. The ingest API rejected a payload over 10MB.",
            )
        if exc.code == 400:
            error_detail = ""
            try:
                error_data = json.loads(body_text)
                error_detail = error_data.get("error", body_text)
                details = error_data.get("details")
                if details:
                    error_detail += f"\n{json.dumps(details, indent=2)}"
            except (json.JSONDecodeError, ValueError):
                error_detail = body_text
            return PushResult(
                success=False,
                status_code=400,
                error_message=f"Bundle failed validation: {error_detail}",
            )
        return PushResult(
            success=False,
            status_code=exc.code,
            error_message=f"API error (HTTP {exc.code}): {body_text}",
        )
    except URLError as exc:
        if "timed out" in str(exc.reason):
            return PushResult(
                success=False,
                error_message=f"Request timed out after 60s connecting to {endpoint}.",
            )
        return PushResult(
            success=False,
            error_message=f"Could not connect to {endpoint}. Check the endpoint URL and your network.",
        )
    except OSError:
        return PushResult(
            success=False,
            error_message=f"Could not connect to {endpoint}. Check the endpoint URL and your network.",
        )


def run_push(
    *,
    endpoint: str | None,
    token: str | None,
    project: str | None,
    root_path: Path,
    quiet: bool = False,
) -> PushResult:
    """Orchestrate a push: resolve config, load bundle, gather git context, POST."""

    git_root = find_git_root(root_path)
    if git_root is None:
        raise click.ClickException("Not a git repository. osoji push requires git context.")

    push_config = resolve_push_config(
        endpoint=endpoint,
        token=token,
        project=project,
        root_path=git_root,
    )

    bundle_path = git_root / ".osoji" / "analysis" / "observatory.json"
    if not bundle_path.exists():
        if not quiet:
            click.echo("Generating observatory bundle...", err=True)
        write_observatory_bundle(git_root)
        if not bundle_path.exists():
            raise click.ClickException(
                "Observatory bundle generation failed. Run 'osoji audit .' first."
            )

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    git_context = gather_git_context(git_root)

    if not quiet:
        click.echo(f"Token loaded from {push_config.token_source}", err=True)
        click.echo(
            f"Pushing {push_config.project_slug} "
            f"@ {git_context.commit[:8]} to {push_config.endpoint}",
            err=True,
        )

    last_commit = _fetch_last_commit(push_config.endpoint, push_config.project_slug, push_config.token)
    commits_since = _get_commits_since(git_root, last_commit)

    envelope = _build_envelope(push_config, git_context, bundle, commits_since)
    result = _post_envelope(push_config.endpoint, push_config.token, envelope)

    if not result.success:
        if result.status_code == 401:
            raise click.ClickException(
                f"Authentication failed. Check the OSOJI_TOKEN value "
                f"(loaded from {push_config.token_source})."
            )
        raise click.ClickException(result.error_message or "Push failed.")

    return result
