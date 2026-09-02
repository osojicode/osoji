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


import json
import tomllib

from .junk_cicd import _parse_makefile

_ECOSYSTEM_BY_MANIFEST: dict[str, str] = {
    "package.json": "npm",
    "Makefile": "make",
    "GNUmakefile": "make",
    "makefile": "make",
    "pyproject.toml": "python",
}


def _scripts_from_package_json(content: str, path: str) -> list[tuple[str, Location]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    lines = content.splitlines()
    out: list[tuple[str, Location]] = []
    for name in scripts:
        line = next((i + 1 for i, l in enumerate(lines) if f'"{name}"' in l), None)
        out.append((str(name), Location(path=path, line=line)))
    return out


def _targets_from_makefile(content: str, path: str) -> list[tuple[str, Location]]:
    return [
        (el.element_name, Location(path=path, line=el.line_start))
        for el in _parse_makefile(content, path)
        if el.element_type == "makefile_target" and not el.element_name.startswith(".")
    ]


def _scripts_from_pyproject(content: str, path: str) -> list[tuple[str, Location]]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []
    scripts = (data.get("project") or {}).get("scripts") or {}
    lines = content.splitlines()
    out: list[tuple[str, Location]] = []
    for name in scripts:
        line = next((i + 1 for i, l in enumerate(lines) if l.strip().startswith(str(name))), None)
        out.append((str(name), Location(path=path, line=line)))
    return out


_PARSERS = {
    "npm": _scripts_from_package_json,
    "make": _targets_from_makefile,
    "python": _scripts_from_pyproject,
}


class ScriptRegistry:
    """Declared runnable names (npm scripts, make targets, pyproject scripts)."""

    namespace = "scripts"

    def __init__(self, entries: dict[str, dict[str, list[Location]]], manifests: dict[str, list[str]]):
        # entries[ecosystem][name] -> locations; manifests[ecosystem] -> searched labels
        self._entries = entries
        self._manifests = manifests

    @classmethod
    def from_config(cls, config: Config) -> "ScriptRegistry":
        entries: dict[str, dict[str, list[Location]]] = {}
        manifests: dict[str, list[str]] = {}
        paths, _ = list_repo_files(config)
        for path in sorted(paths):
            p = path if path.is_absolute() else config.root_path / path
            eco = _ECOSYSTEM_BY_MANIFEST.get(p.name)
            if eco is None or not p.is_file():
                continue
            rel = _norm_rel(str(p.relative_to(config.root_path)))
            try:
                content = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            label = f"{rel}#scripts" if eco in ("npm", "python") else f"{rel}#targets"
            manifests.setdefault(eco, []).append(label)
            for name, loc in _PARSERS[eco](content, rel):
                entries.setdefault(eco, {}).setdefault(name, []).append(loc)
        return cls(entries, manifests)

    @property
    def manifests(self) -> list[str]:
        return sorted(label.split("#")[0] for labels in self._manifests.values() for label in labels)

    def exists(self, name: str, ecosystem: str | None = None) -> RegistryAnswer:
        ecos = [ecosystem] if ecosystem else sorted(self._entries) or sorted(self._manifests)
        searched = [label for eco in ecos for label in self._manifests.get(eco, [])]
        if not searched:
            return RegistryAnswer(name=name, found=False, namespace=self.namespace, searched=[], complete=False)
        locations = [loc for eco in ecos for loc in self._entries.get(eco, {}).get(name, [])]
        universe = sorted({n for eco in ecos for n in self._entries.get(eco, {})})
        return RegistryAnswer(
            name=name,
            found=bool(locations),
            locations=locations,
            near=[] if locations else _near(name, universe),
            namespace=self.namespace,
            searched=searched,
            complete=True,
        )
