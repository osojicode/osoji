"""Mechanical fact registries (Tier A of decisions/0031).

A registry answers closed-world questions about the checkout -- "does this
path exist", "is this script declared" -- from parsers, never from LLM text.
Every answer carries the namespace that was searched and the near matches, so
absence is an auditable query rather than a retrieval miss.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .walker import _matches_ignore, list_repo_files


@dataclass(frozen=True)
class Location:
    path: str
    line: int | None = None


@dataclass
class RegistryAnswer:
    name: str
    found: bool
    locations: list[Location] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    namespace: str = ""
    searched: list[str] = field(default_factory=list)
    complete: bool = True  # False when the namespace could not be built


def _norm_rel(p: str) -> str:
    s = p.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _near(name: str, universe: list[str], n: int = 3) -> list[str]:
    return difflib.get_close_matches(name, universe, n=n, cutoff=0.6)


class PathRegistry:
    """Every tracked file and every ancestor directory, walker-filtered."""

    namespace = "paths"

    def __init__(self, entries: set[str]) -> None:
        self._entries = entries
        self._sorted = sorted(entries)

    @classmethod
    def from_config(cls, config: Config) -> "PathRegistry":
        entries: set[str] = set()
        osojiignore = config.load_osojiignore()
        paths, _used_git = list_repo_files(config)
        for path in paths:
            p = path if path.is_absolute() else config.root_path / path
            try:
                relative = p.relative_to(config.root_path)
            except ValueError:
                continue
            # list_repo_files only filters by .gitignore (or does a raw walk);
            # default ignore patterns (node_modules, vendor, .osoji, ...) and
            # .osojiignore are applied here, matching every other consumer of
            # list_repo_files in the codebase (discover_files, deadcode.py, etc).
            if _matches_ignore(relative, config.ignore_patterns):
                continue
            if osojiignore and _matches_ignore(relative, osojiignore):
                continue
            rel = _norm_rel(str(relative))
            if not rel:
                continue
            entries.add(rel)
            parent = Path(rel).parent
            while str(parent) not in ("", "."):
                entries.add(_norm_rel(str(parent)))
                parent = parent.parent
        return cls(entries)

    @property
    def size(self) -> int:
        return len(self._entries)

    def exists(self, rel_path: str) -> RegistryAnswer:
        name = _norm_rel(rel_path)
        found = name in self._entries
        return RegistryAnswer(
            name=name,
            found=found,
            locations=[Location(path=name)] if found else [],
            near=[] if found else _near(name, self._sorted),
            namespace=self.namespace,
            searched=["git-tracked tree (walker-filtered)"],
            complete=True,
        )
