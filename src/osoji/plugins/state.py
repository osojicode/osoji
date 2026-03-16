"""Plugin extraction staleness tracking.

Stores per-plugin state so re-extraction can be skipped when no files changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import SHADOW_DIR
from ..hasher import compute_file_hash


@dataclass
class PluginExtractionState:
    """Persisted state for a single plugin's last extraction run."""

    plugin_name: str
    extracted_at: str  # ISO timestamp
    file_count: int
    project_hash: str  # sha256 of sorted source hashes


def _state_path(project_root: Path) -> Path:
    return project_root / SHADOW_DIR / "plugin_state.json"


def _compute_project_hash(files: list[Path]) -> str:
    """Compute a hash over all applicable file hashes (sorted for determinism)."""
    hashes = sorted(compute_file_hash(f) for f in files)
    combined = hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()[:16]
    return combined


def load_plugin_state(project_root: Path) -> dict[str, PluginExtractionState]:
    """Load all plugin states from disk."""
    path = _state_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            name: PluginExtractionState(**entry)
            for name, entry in data.items()
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def save_plugin_state(
    project_root: Path,
    states: dict[str, PluginExtractionState],
) -> None:
    """Persist all plugin states to disk."""
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {name: asdict(state) for name, state in states.items()}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_plugin_stale(
    project_root: Path,
    plugin_name: str,
    applicable_files: list[Path],
) -> bool:
    """Check if a plugin needs re-extraction.

    Returns True if any applicable file has changed since last extraction.
    """
    states = load_plugin_state(project_root)
    state = states.get(plugin_name)
    if not state:
        return True

    current_hash = _compute_project_hash(applicable_files)
    return current_hash != state.project_hash


def record_plugin_extraction(
    project_root: Path,
    plugin_name: str,
    applicable_files: list[Path],
) -> None:
    """Record that a plugin extraction just completed."""
    states = load_plugin_state(project_root)
    states[plugin_name] = PluginExtractionState(
        plugin_name=plugin_name,
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        file_count=len(applicable_files),
        project_hash=_compute_project_hash(applicable_files),
    )
    save_plugin_state(project_root, states)
