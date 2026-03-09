"""Utilities for loading and querying public symbol data from shadow doc sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config, SHADOW_DIR


def _is_source_doc_candidate(config: Config, source: str) -> bool:
    return config.is_doc_candidate(Path(source))


def load_all_symbols(config: Config) -> dict[str, list[dict]]:
    """Load all public symbols across the project.

    Reads every *.symbols.json file under .osoji/symbols/ and returns
    a dict mapping relative source file paths to their symbol lists.

    Each symbol dict has keys: name, kind, line_start, and optionally line_end.
    """
    symbols_dir = config.root_path / SHADOW_DIR / "symbols"
    if not symbols_dir.exists():
        return {}

    result: dict[str, list[dict]] = {}
    for symbols_file in symbols_dir.rglob("*.symbols.json"):
        try:
            data = json.loads(symbols_file.read_text(encoding="utf-8"))
            source = data.get("source")
            symbols = data.get("symbols", [])
            if source and symbols and not _is_source_doc_candidate(config, source):
                result[source] = symbols
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return result


def load_file_roles(config: Config) -> dict[str, str]:
    """Load file_role for every file with a symbols JSON sidecar.

    Returns dict mapping relative source path -> role string.
    Files without file_role key (old cache) are omitted.
    """
    symbols_dir = config.root_path / SHADOW_DIR / "symbols"
    if not symbols_dir.exists():
        return {}

    result: dict[str, str] = {}
    for symbols_file in symbols_dir.rglob("*.symbols.json"):
        try:
            data = json.loads(symbols_file.read_text(encoding="utf-8"))
            source = data.get("source")
            role = data.get("file_role")
            if source and role and not _is_source_doc_candidate(config, source):
                result[source] = role
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return result


def load_files_by_role(config: Config, role: str) -> list[str]:
    """Return relative source paths classified with the given role.

    Example: load_files_by_role(config, "schema")
    """
    all_roles = load_file_roles(config)
    return [path for path, r in all_roles.items() if r == role]
