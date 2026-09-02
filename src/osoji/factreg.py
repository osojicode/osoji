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
from .walker import (
    _matches_exclude_pattern,
    _matches_ignore,
    is_under_corpus_snapshot,
    list_repo_files,
)


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
    # Why the namespace is incomplete for *this* query, in the registry's own
    # words. An incomplete answer is a statement about the index, not about
    # the world, and the caller has to be able to say which.
    note: str = ""


def _norm_rel(p: str) -> str:
    s = p.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _near(name: str, universe: list[str], n: int = 3) -> list[str]:
    return difflib.get_close_matches(name, universe, n=n, cutoff=0.6)


# difflib scores the query against every candidate handed to it, so the
# candidate set -- not the tree -- is what bounds a near-match lookup.
_NEAR_CANDIDATE_CAP = 2000


class PathRegistry:
    """Every tracked file and every ancestor directory, walker-filtered.

    The walker's filter is a *source-discovery* filter, not the checkout: it
    drops ignored prefixes, ``.osojiignore`` and ``[audit] exclude`` matches,
    corpus-case snapshots, and (via git) everything ``.gitignore`` hides. Those
    regions hold real, tracked files, so a miss inside one is a gap in the
    index rather than evidence of absence. The registry therefore carries the
    filter that built it and reports such a miss as an *incomplete* answer --
    the caller renders it ``undecidable``, never ``contradicted``.
    """

    namespace = "paths"

    def __init__(
        self,
        entries: set[str],
        root: Path | None = None,
        ignore_patterns: set[str] | None = None,
        osojiignore: list[str] | None = None,
        exclude_globs: list[str] | None = None,
    ) -> None:
        self._entries = entries
        self._root = root
        self._ignore_patterns: set[str] = set(ignore_patterns or ())
        self._osojiignore: list[str] = list(osojiignore or ())
        self._exclude_globs: list[str] = list(exclude_globs or ())
        self._corpus_cache: dict[Path, bool] = {}
        self._dir_names: dict[Path, frozenset[str]] = {}
        # Every name that appears as a first path segment -- the repository's
        # top-level entries, files and directories alike. See `anchored`.
        self._top_level: set[str] = {entry.split("/", 1)[0] for entry in entries}
        # Buckets for bounded near-match candidates (see near_candidates).
        self._by_parent: dict[str, list[str]] = {}
        self._by_basename: dict[str, list[str]] = {}
        for entry in sorted(entries):
            parent, _, base = entry.rpartition("/")
            self._by_parent.setdefault(parent, []).append(entry)
            self._by_basename.setdefault(base.lower(), []).append(entry)

    @classmethod
    def from_config(cls, config: Config) -> "PathRegistry":
        entries: set[str] = set()
        osojiignore = config.load_osojiignore()
        try:
            exclude_globs = config.load_audit_exclude()
        except RuntimeError:
            # A malformed `[audit] exclude` is the walker's problem to report;
            # here it only means "no glob filter to re-derive".
            exclude_globs = []
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
        return cls(
            entries,
            root=config.root_path,
            ignore_patterns=set(config.ignore_patterns),
            osojiignore=osojiignore,
            exclude_globs=exclude_globs,
        )

    @property
    def size(self) -> int:
        return len(self._entries)

    def near_candidates(self, name: str) -> list[str]:
        """The bounded candidate set a near-match lookup is scored against.

        ``difflib`` scores the query against every candidate it is given, so
        handing it the whole tree makes each miss cost O(tree) -- and misses
        are what this layer produces in bulk. A path that differs from a real
        one by a typo shares either its parent directory or its basename, so
        those two buckets are the whole useful search space; they are bounded
        by directory width instead of tree size, and capped besides.
        """
        parent, _, base = name.rpartition("/")
        seen: set[str] = set()
        out: list[str] = []
        for bucket in (self._by_parent.get(parent, ()), self._by_basename.get(base.lower(), ())):
            for entry in bucket:
                if entry in seen:
                    continue
                seen.add(entry)
                out.append(entry)
                if len(out) >= _NEAR_CANDIDATE_CAP:
                    return out
        return out

    def outside_index(self, name: str) -> str | None:
        """Why ``name`` is outside the index, or None if the index covers it.

        A returned reason means the registry cannot speak to this path: the
        region it lives in was filtered out before indexing, so "not in the
        entries set" carries no information about whether the file exists.
        """
        relative = Path(name)
        if ".." in relative.parts:
            return "path escapes the repository root"
        matched = _matches_ignore(relative, self._ignore_patterns)
        if matched:
            return f"path lies under the ignored prefix '{matched}'"
        if self._osojiignore:
            matched = _matches_ignore(relative, self._osojiignore)
            if matched:
                return f"path is excluded by the .osojiignore pattern '{matched}'"
        if self._exclude_globs and _matches_exclude_pattern(name, self._exclude_globs):
            return "path is excluded by an [audit] exclude glob"
        if self._root is None:
            return None
        candidate = self._root / relative
        try:
            if is_under_corpus_snapshot(candidate, self._root, self._corpus_cache):
                return "path lies under a corpus-case snapshot"
            if candidate.exists() and self._present_case_exact(name):
                return "path is present in the working tree but outside the indexed universe"
        except (OSError, ValueError):
            return None
        return None

    def _present_case_exact(self, name: str) -> bool:
        """True only when every segment of ``name`` matches the on-disk casing.

        ``Path.exists()`` is case-insensitive on Windows and on a default macOS
        volume while the entry set is case-sensitive, so a case-error claim
        (`docs/Guide.md` for `docs/guide.md`) would read ``undecidable`` on a
        dev box and ``contradicted`` on Linux CI -- from the same checkout.
        Zero LLM calls means every verdict is reproducible from the checkout
        alone, and that has to include reproducible across hosts, so presence
        is confirmed segment by segment against the real directory listings.
        A case error in a doc path is also precisely the drift that builds on
        one filesystem and breaks on another, so it is a finding worth keeping.
        """
        assert self._root is not None
        current = self._root
        for segment in name.split("/"):
            names = self._dir_names.get(current)
            if names is None:
                try:
                    names = frozenset(entry.name for entry in current.iterdir())
                except OSError:
                    return False
                self._dir_names[current] = names
            if segment not in names:
                return False
            current = current / segment
        return True

    def anchored(self, name: str) -> bool:
        """True when ``name``'s first segment is a top-level entry of the tree.

        A repo-relative path claim is decidable only if its root is in the
        repository: `src/nope.ts` in a tree that has `src/` is a claim about
        this checkout and can be contradicted, while `tools/list` in a tree
        with no `tools` never addressed the checkout at all. The unanchored
        shape is what foreign namespaces have in common -- RPC method names,
        `org/repo` slugs, `vendor/model` ids, container image refs, paths
        quoted from another repository -- and the principle (a claim whose
        root is absent is not a claim about this tree) covers all of them
        without enumerating any.
        """
        return name.split("/", 1)[0] in self._top_level

    def exists(self, rel_path: str) -> RegistryAnswer:
        name = _norm_rel(rel_path)
        searched = ["git-tracked tree (walker-filtered)"]
        if name in self._entries:
            return RegistryAnswer(
                name=name,
                found=True,
                locations=[Location(path=name)],
                namespace=self.namespace,
                searched=searched,
                complete=True,
            )
        reason = self.outside_index(name)
        if reason is not None:
            return RegistryAnswer(
                name=name,
                found=False,
                namespace=self.namespace,
                searched=searched,
                complete=False,
                note=f"{reason}; absence cannot be established",
            )
        if not self.anchored(name):
            return RegistryAnswer(
                name=name,
                found=False,
                namespace=self.namespace,
                searched=searched,
                complete=False,
                note="root segment not in the tree; not a repo-relative claim",
            )
        return RegistryAnswer(
            name=name,
            found=False,
            near=_near(name, self.near_candidates(name)),
            namespace=self.namespace,
            searched=searched,
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
    # `[project]` need not be a table in syntactically-valid TOML (``project =
    # "foo"`` parses fine), so mirror _scripts_from_package_json's shape check
    # rather than assuming a mapping.
    project = data.get("project")
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if not isinstance(scripts, dict):
        return []
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
        osojiignore = config.load_osojiignore()
        paths, _ = list_repo_files(config)
        for path in sorted(paths):
            p = path if path.is_absolute() else config.root_path / path
            eco = _ECOSYSTEM_BY_MANIFEST.get(p.name)
            if eco is None or not p.is_file():
                continue
            try:
                relative = p.relative_to(config.root_path)
            except ValueError:
                continue
            # list_repo_files only filters by .gitignore (or does a raw walk);
            # default ignore patterns (node_modules, vendor, .osoji, ...) and
            # .osojiignore are applied here, matching PathRegistry.from_config
            # and every other consumer of list_repo_files in the codebase
            # (discover_files, deadcode.py, etc) -- otherwise a dependency's
            # own manifest (e.g. a vendored package.json) would be treated as
            # a first-party project manifest.
            if _matches_ignore(relative, config.ignore_patterns):
                continue
            if osojiignore and _matches_ignore(relative, osojiignore):
                continue
            rel = _norm_rel(str(relative))
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
