"""Interactive project setup for Osoji."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .config import PROJECT_CONFIG_FILENAME

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

    for key, value in values.items():
        if key in existing_keys:
            actions.append({"key": key, "action": "skipped", "reason": "already set in .env"})
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
