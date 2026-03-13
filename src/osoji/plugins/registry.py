"""Plugin registry — maps file extensions to language plugins."""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LanguagePlugin

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, "LanguagePlugin"] = {}  # extension -> plugin


def register_plugin(plugin: "LanguagePlugin") -> None:
    """Register a plugin for all its declared extensions."""
    for ext in plugin.extensions:
        _REGISTRY[ext] = plugin


def plugin_for(path: str | Path) -> "LanguagePlugin | None":
    """Look up the plugin for a file path by its suffix."""
    suffix = Path(path).suffix
    return _REGISTRY.get(suffix)


def supported_extensions() -> frozenset[str]:
    """Return all extensions with a registered plugin."""
    return frozenset(_REGISTRY.keys())


def get_all_plugins() -> list["LanguagePlugin"]:
    """Return deduplicated list of all registered plugins."""
    seen_ids: set[int] = set()
    result: list["LanguagePlugin"] = []
    for plugin in _REGISTRY.values():
        pid = id(plugin)
        if pid not in seen_ids:
            seen_ids.add(pid)
            result.append(plugin)
    return result


def _reset_registry() -> None:
    """Clear all registered plugins. For testing only."""
    _REGISTRY.clear()


def _discover_entry_point_plugins() -> None:
    """Discover and register plugins from 'osoji.plugins' entry points."""
    try:
        eps = importlib.metadata.entry_points(group="osoji.plugins")
    except Exception:
        return

    for ep in eps:
        try:
            plugin_cls = ep.load()
            plugin = plugin_cls()
            register_plugin(plugin)
            logger.debug(f"Loaded entry-point plugin: {ep.name} -> {plugin.name}")
        except Exception as e:
            logger.warning(f"Failed to load entry-point plugin {ep.name!r}: {e}")
