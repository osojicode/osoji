"""Interactive project setup for Osoji."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import click

from .config import PROJECT_CONFIG_FILENAME
from .llm.registry import get_provider_spec
from .push import _infer_project_from_git_remote

_GITIGNORE_ENTRIES: list[tuple[str, str]] = [
    (".osoji/", "intermediate results and derived data"),
    (".osoji.local.toml", "local config overrides"),
    (".env", "secrets file"),
]


def merge_gitignore(root: Path) -> list[dict[str, str]]:
    """Ensure .gitignore has osoji entries. Returns actions taken per entry."""

    gitignore_path = root / ".gitignore"
    existing_lines: set[str] = set()
    original = ""

    if gitignore_path.exists():
        original = gitignore_path.read_text(encoding="utf-8")
        existing_lines = {line.strip() for line in original.splitlines()}

    actions: list[dict[str, str]] = []
    to_add: list[str] = []

    for pattern, description in _GITIGNORE_ENTRIES:
        if pattern in existing_lines:
            actions.append({"entry": pattern, "action": "skipped", "reason": "already in .gitignore"})
        else:
            to_add.append(pattern)
            actions.append({"entry": pattern, "action": "added", "description": description})

    if to_add:
        lines: list[str] = []
        if original and not original.endswith("\n"):
            lines.append("")
        lines.append("")
        lines.append("# Osoji")
        lines.extend(to_add)
        lines.append("")

        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    return actions


def _parse_env_keys(content: str) -> set[str]:
    """Extract active (non-commented) variable names from .env content."""

    keys: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", stripped)
            if match:
                keys.add(match.group(1))
    return keys


def merge_dotenv(root: Path, values: dict[str, str]) -> list[dict[str, str]]:
    """Merge key=value pairs into .env, skipping keys already present.

    Empty values are written as commented-out lines (# KEY=).
    """

    env_path = root / ".env"
    existing_keys: set[str] = set()
    original = ""

    if env_path.exists():
        original = env_path.read_text(encoding="utf-8")
        existing_keys = _parse_env_keys(original)

    actions: list[dict[str, str]] = []
    lines_to_add: list[str] = []

    # Also track commented-out placeholders to avoid duplicating them
    commented_keys: set[str] = set()
    if original:
        for line in original.splitlines():
            stripped = line.strip()
            cm = re.match(r"#\s*([A-Za-z_][A-Za-z0-9_]*)=", stripped)
            if cm:
                commented_keys.add(cm.group(1))

    for key, value in values.items():
        if key in existing_keys:
            actions.append({"key": key, "action": "skipped", "reason": "already set in .env"})
        elif not value and key in commented_keys:
            actions.append({"key": key, "action": "skipped", "reason": "placeholder already in .env"})
        else:
            if value:
                lines_to_add.append(f"{key}={value}")
            else:
                lines_to_add.append(f"# {key}=")
            actions.append({"key": key, "action": "added"})

    if lines_to_add:
        parts: list[str] = []
        if original and not original.endswith("\n"):
            parts.append("")
        parts.extend(lines_to_add)
        parts.append("")

        with open(env_path, "a", encoding="utf-8") as f:
            f.write("\n".join(parts))

    return actions


def merge_project_toml(root: Path, *, project_slug: str | None) -> list[dict[str, str]]:
    """Ensure .osoji.toml has a [push] project entry."""

    if not project_slug:
        return [{"key": "push.project", "action": "skipped", "reason": "no project slug provided"}]

    toml_path = root / PROJECT_CONFIG_FILENAME
    existing: dict = {}

    if toml_path.exists():
        try:
            existing = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            existing = {}

    push = existing.get("push")
    if isinstance(push, dict) and "project" in push:
        return [{"key": "push.project", "action": "skipped",
                 "reason": f"already set in {PROJECT_CONFIG_FILENAME}"}]

    original = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
    parts: list[str] = []
    if original and not original.endswith("\n"):
        parts.append("")
    parts.append("")
    parts.append("[push]")
    parts.append(f'project = "{project_slug}"')
    parts.append("")

    with open(toml_path, "a", encoding="utf-8") as f:
        f.write("\n".join(parts))

    return [{"key": "push.project", "action": "added"}]


def run_init(
    *,
    root: Path,
    interactive: bool = True,
    provider: str = "anthropic",
) -> None:
    """Orchestrate osoji project setup."""

    click.echo()
    click.echo("Osoji project setup")
    click.echo("=" * 40)

    # --- 1. Git hygiene ---
    click.echo()
    click.echo(click.style("1. Git hygiene", bold=True))

    if interactive:
        entries_to_add: list[tuple[str, str]] = []

        for pattern, description in _GITIGNORE_ENTRIES:
            gitignore_path = root / ".gitignore"
            existing_lines: set[str] = set()
            if gitignore_path.exists():
                existing_lines = {
                    line.strip()
                    for line in gitignore_path.read_text(encoding="utf-8").splitlines()
                }

            if pattern in existing_lines:
                click.echo(f"   Already in .gitignore: {pattern}")
                continue

            if click.confirm(
                f"   Add {pattern} to .gitignore? ({description})",
                default=True,
            ):
                entries_to_add.append((pattern, description))

        if entries_to_add:
            gitignore_path = root / ".gitignore"
            original = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
            parts: list[str] = []
            if original and not original.endswith("\n"):
                parts.append("")
            parts.append("")
            parts.append("# Osoji")
            for pattern, _ in entries_to_add:
                parts.append(pattern)
            parts.append("")
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n".join(parts))
            for pattern, _ in entries_to_add:
                click.echo(f"   {click.style('ok', fg='green')} Added {pattern}")
    else:
        actions = merge_gitignore(root)
        for a in actions:
            if a["action"] == "added":
                click.echo(f"   {click.style('ok', fg='green')} Added {a['entry']}")
            else:
                click.echo(f"   Already in .gitignore: {a['entry']}")

    # --- 2. Secrets (.env) ---
    click.echo()
    click.echo(click.style("2. Secrets (.env)", bold=True))

    spec = get_provider_spec(provider)
    api_key_env = spec.api_key_env

    env_values: dict[str, str] = {}

    if interactive:
        env_path = root / ".env"
        existing_keys: set[str] = set()
        if env_path.exists():
            existing_keys = _parse_env_keys(env_path.read_text(encoding="utf-8"))

        click.echo(f"   LLM provider: {provider}")

        if api_key_env:
            if api_key_env in existing_keys:
                click.echo(f"   Skipping {api_key_env} in .env (already set)")
            elif click.confirm(f"   Set {api_key_env}?", default=True):
                value = click.prompt(f"   {api_key_env}", default="", hide_input=True)
                env_values[api_key_env] = value

        if "OSOJI_TOKEN" in existing_keys:
            click.echo(f"   Skipping OSOJI_TOKEN in .env (already set)")
        elif click.confirm(f"   Set OSOJI_TOKEN? (needed for `osoji push`)", default=True):
            value = click.prompt(f"   OSOJI_TOKEN", default="", hide_input=True)
            env_values["OSOJI_TOKEN"] = value

        if env_values:
            env_actions = merge_dotenv(root, env_values)
            for a in env_actions:
                if a["action"] == "added":
                    click.echo(f"   {click.style('ok', fg='green')} Added {a['key']} to .env")
                else:
                    click.echo(f"   Skipping {a['key']} in .env ({a['reason']})")
        elif not existing_keys:
            click.echo("   No secrets configured.")
    else:
        if api_key_env:
            env_values[api_key_env] = ""
        env_values["OSOJI_TOKEN"] = ""
        actions = merge_dotenv(root, env_values)
        for a in actions:
            if a["action"] == "added":
                click.echo(f"   {click.style('ok', fg='green')} Added {a['key']} to .env (placeholder)")
            else:
                click.echo(f"   Skipping {a['key']} in .env ({a['reason']})")

    # --- 3. Project config (.osoji.toml) ---
    click.echo()
    click.echo(click.style("3. Project config (.osoji.toml)", bold=True))

    inferred_slug = _infer_project_from_git_remote(root)

    if interactive:
        default_slug = inferred_slug or ""
        project_slug = click.prompt(
            "   Project slug (for `osoji push`)",
            default=default_slug,
        )
        project_slug = project_slug.strip() or None
    else:
        project_slug = inferred_slug

    toml_actions = merge_project_toml(root, project_slug=project_slug)
    for a in toml_actions:
        if a["action"] == "added":
            click.echo(f"   {click.style('ok', fg='green')} Set [push] project = \"{project_slug}\" in .osoji.toml")
        else:
            click.echo(f"   Skipping {a['key']} ({a['reason']})")

    # --- Done ---
    click.echo()
    click.echo(click.style("Done!", bold=True) + " Next steps:")
    click.echo("  osoji audit . --dry-run    Preview what osoji will analyze")
    click.echo("  osoji audit .              Run a full audit")
    click.echo("  osoji config show          See resolved configuration")
    click.echo()
