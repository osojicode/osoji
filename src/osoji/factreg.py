"""Mechanical fact registries (Tier A of decisions/0031).

A registry answers closed-world questions about the checkout -- "does this
path exist", "is this script declared" -- from parsers, never from LLM text.
Every answer carries the namespace that was searched and the near matches, so
absence is an auditable query rather than a retrieval miss.
"""

from __future__ import annotations

import difflib
import subprocess
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

    def gitignored(self, names: list[str]) -> list[str]:
        """Which of ``names`` git would ignore -- for paths that do not exist.

        ``git check-ignore --no-index`` matches the patterns without needing
        the path on disk, which is the case that matters: a gitignored module
        that a build would generate is absent from a bare checkout, and its
        absence is not evidence. Empty when the root is not a git checkout.
        """
        if self._root is None or not names:
            return []
        try:
            out = subprocess.run(
                ["git", "check-ignore", "--no-index", "--", *names],
                cwd=self._root, capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if out.returncode not in (0, 1):
            return []
        return [line.strip().replace("\\", "/") for line in out.stdout.splitlines() if line.strip()]

    def has_entry(self, name: str) -> bool:
        """O(1) membership check against the indexed entries.

        Used by doc-relative anchor checks (tier_a.py), which only need to
        know "is this directory real" -- not the full `exists()` answer
        (found/near/locations/searched), so they should not pay for a
        difflib near-match search on every miss.
        """
        return _norm_rel(name) in self._entries

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

    def exists(self, rel_path: str, *, anchor: bool = True) -> RegistryAnswer:
        """Whether ``rel_path`` is in the index, with the reason when it cannot say.

        ``anchor=False`` skips the anchor rule: a code import's relative
        specifier has no foreign reading (it is a path in this tree by
        construction), so a miss is a miss even when the resolved root
        segment does not exist.
        """
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
        if anchor and not self.anchored(name):
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
import re
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


# `include`, `-include` and `sinclude` pull targets in from other files the
# registry does not index: a miss against such a Makefile is incomplete.
_MAKE_INCLUDE_RE = re.compile(r"^\s*-?s?include\s", re.MULTILINE)


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

    def __init__(self, entries: dict[str, dict[str, list[Location]]], manifests: dict[str, list[str]],
                 incomplete: dict[str, str] | None = None):
        # entries[ecosystem][name] -> locations; manifests[ecosystem] -> searched labels;
        # incomplete[ecosystem] -> why a miss in that namespace is not an absence
        self._entries = entries
        self._manifests = manifests
        self._incomplete = incomplete or {}

    @classmethod
    def from_config(cls, config: Config) -> "ScriptRegistry":
        entries: dict[str, dict[str, list[Location]]] = {}
        manifests: dict[str, list[str]] = {}
        incomplete: dict[str, str] = {}
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
            if eco == "make" and _MAKE_INCLUDE_RE.search(content):
                incomplete.setdefault(eco, f"{rel} includes other makefiles; targets declared there are not indexed")
        return cls(entries, manifests, incomplete)

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
        if not locations:
            notes = [self._incomplete[eco] for eco in ecos if eco in self._incomplete]
            if notes:
                return RegistryAnswer(
                    name=name, found=False, near=_near(name, universe), namespace=self.namespace,
                    searched=searched, complete=False, note="; ".join(notes),
                )
        return RegistryAnswer(
            name=name,
            found=bool(locations),
            locations=locations,
            near=[] if locations else _near(name, universe),
            namespace=self.namespace,
            searched=searched,
            complete=True,
        )


# ---------------------------------------------------------------------------
# Symbol registry: declarations, members and module resolution from the
# language plugins' structure facts (osoji.plugins.base, ``extract_structure``).
# Language-agnostic: the plugin knows its syntax and its module-specifier
# conventions; this registry only knows names, members and files.
# ---------------------------------------------------------------------------

import posixpath
from typing import Callable


@dataclass
class Declaration:
    name: str
    kind: str                 # enum | interface | type | class | object | function | variable
    file: str
    line: int
    exported: bool = False
    members: list[dict] | None = None      # None: no member set (variable, function)
    open: bool = False                     # index signature / spread / computed key: not a closed set
    extends: list[str] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    annotation: str | None = None          # declared or `satisfies`/`as` type of an object literal
    params: list[dict] = field(default_factory=list)

    @property
    def member_names(self) -> list[str]:
        return [m["name"] for m in (self.members or [])]


@dataclass
class ResolvedModule:
    kind: str                 # file | missing | external | outside | unindexed
    file: str | None = None
    candidates: list[str] = field(default_factory=list)
    note: str = ""


_TYPE_KINDS = {"interface", "type", "class", "enum"}


class SymbolRegistry:
    """Declared symbols and their members, plus per-file import/export resolution."""

    namespace = "symbols"

    def __init__(
        self,
        structure: dict[str, dict],
        *,
        module_candidates: Callable[[str], list[str]],
        workspace_packages: dict[str, str] | None,
        paths: PathRegistry,
    ) -> None:
        self._structure = structure
        self._module_candidates = module_candidates
        self._workspace = dict(workspace_packages or {})
        self._paths = paths
        self._decls: dict[str, list[Declaration]] = {}
        self._by_name: dict[tuple[str, str], list[Declaration]] = {}
        self._by_callable: dict[str, list[tuple[Declaration, list[dict]]]] = {}
        for file, facts in structure.items():
            local_exports = {e["name"] for e in facts.get("local_exports", [])}
            decls: list[Declaration] = []
            for d in facts.get("declarations", []):
                decl = Declaration(
                    name=d["name"], kind=d["kind"], file=file, line=int(d.get("line") or 0),
                    exported=bool(d.get("exported")) or d["name"] in local_exports,
                    members=d.get("members"), open=bool(d.get("open")),
                    extends=list(d.get("extends") or []), implements=list(d.get("implements") or []),
                    annotation=d.get("annotation"), params=list(d.get("params") or []),
                )
                decls.append(decl)
                self._by_name.setdefault((decl.name, decl.kind), []).append(decl)
                if decl.kind == "function":
                    self._by_callable.setdefault(decl.name, []).append((decl, decl.params))
                if decl.kind == "class":
                    for m in decl.members or []:
                        if m.get("kind") == "method" and "param_list" in m:
                            self._by_callable.setdefault(m["name"], []).append((decl, list(m["param_list"])))
            self._decls[file] = decls
        self._resolve_cache: dict[tuple[str, str], ResolvedModule] = {}

    @classmethod
    def from_structure(cls, structure, *, module_candidates, workspace_packages, paths) -> "SymbolRegistry":
        return cls(structure, module_candidates=module_candidates, workspace_packages=workspace_packages, paths=paths)

    @property
    def files(self) -> list[str]:
        return sorted(self._structure)

    def facts(self, file: str) -> dict:
        return self._structure.get(file, {})

    def declarations(self, file: str) -> list[Declaration]:
        return self._decls.get(file, [])

    def declarations_named(self, name: str, kinds: set[str] | None = None) -> list[Declaration]:
        out: list[Declaration] = []
        for (n, k), ds in self._by_name.items():
            if n == name and (kinds is None or k in kinds):
                out.extend(ds)
        return out

    def callables_named(self, name: str) -> list[tuple[Declaration, list[dict]]]:
        """Every in-repo function or method declared with this name: (owner, params)."""
        return list(self._by_callable.get(name, []))

    def local_type(self, file: str, name: str) -> tuple[str | None, str]:
        """The type a local/parameter/property named ``name`` is declared or constructed with."""
        types = {l["type"] for l in self._structure.get(file, {}).get("locals", []) if l.get("name") == name and l.get("type")}
        if not types:
            return None, f"`{name}` has no declared or constructed type in the file"
        if len(types) > 1:
            return None, f"`{name}` is declared with more than one type in the file ({', '.join(sorted(types))})"
        return next(iter(types)), ""

    def method_of(self, decl: Declaration, name: str) -> tuple[Declaration, dict] | None:
        """``name`` as a method member of ``decl`` or an in-repo base, with its parameter list."""
        members, _open, _unresolved = self.member_set(decl)
        m = members.get(name)
        if not m or m.get("kind") != "method" or "param_list" not in m:
            return None
        owner = decl
        if m not in (decl.members or []):
            for d in self._walk_bases(decl):
                if m in (d.members or []):
                    owner = d
                    break
        return owner, list(m["param_list"])

    def _walk_bases(self, decl: Declaration, seen: set | None = None) -> list[Declaration]:
        seen = seen if seen is not None else set()
        out: list[Declaration] = []
        for base_name in decl.extends:
            base, _ = self.resolve_type(decl.file, base_name)
            if base is None or (base.file, base.name) in seen:
                continue
            seen.add((base.file, base.name))
            out.append(base)
            out.extend(self._walk_bases(base, seen))
        return out

    def resolve_callee(self, file: str, call: dict) -> tuple[list[tuple[Declaration, list[dict], int]], str]:
        """The declaration(s) a call binds to through its receiver: [(owner, params, line)], or ([], why).

        A bare ``f(...)`` binds ``f``; ``this.m(...)`` binds the enclosing class;
        ``x.m(...)`` binds ``x``'s declared or constructed type, then ``m`` on it
        (walking in-repo bases). Nothing is resolved by name alone.
        """
        member = call.get("member")
        receiver = call.get("receiver")
        if not member:
            return [], "callee is not a name"
        if receiver is None:
            decl, why = self.bind(file, member)
            if decl is None:
                return [], why
            if decl.kind != "function":
                return [], f"`{member}` binds to a {decl.kind}, not a function"
            return [(decl, decl.params, decl.line)], ""
        if receiver == "this":
            cls_name = call.get("enclosing_class")
            if not cls_name:
                return [], "`this` outside a class body"
            owner = next((d for d in self._decls.get(file, []) if d.kind == "class" and d.name == cls_name), None)
            if owner is None:
                return [], f"enclosing class `{cls_name}` not found"
        elif receiver == "<expression>":
            return [], "receiver is an expression, not a name"
        else:
            type_name, why = self.local_type(file, receiver)
            if type_name is None:
                return [], why
            owner, why = self.resolve_type(file, type_name)
            if owner is None:
                return [], why or f"`{type_name}` does not resolve in the repository"
            if owner.kind not in ("class", "interface"):
                return [], f"`{type_name}` is a {owner.kind}, not a class or interface"
        found = self.method_of(owner, member)
        if found is None:
            return [], f"`{owner.name}` declares no method `{member}` in the repository"
        real_owner, params = found
        line = next((int(m.get("line") or real_owner.line) for m in (real_owner.members or []) if m.get("name") == member), real_owner.line)
        return [(real_owner, params, line)], ""

    # -- module resolution ---------------------------------------------------

    def resolve_specifier(self, from_file: str, specifier: str) -> ResolvedModule:
        key = (from_file, specifier)
        if key not in self._resolve_cache:
            self._resolve_cache[key] = self._resolve_specifier(from_file, specifier)
        return self._resolve_cache[key]

    def _resolve_specifier(self, from_file: str, specifier: str) -> ResolvedModule:
        if specifier.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), specifier))
            if base == ".." or base.startswith("../"):
                return ResolvedModule("outside", note="specifier resolves outside the repository root")
            return self._resolve_base(base)
        for pkg, src_dir in sorted(self._workspace.items(), key=lambda kv: -len(kv[0])):
            if specifier == pkg or specifier.startswith(pkg + "/"):
                sub = specifier[len(pkg) + 1:]
                if sub:
                    return self._resolve_base(_norm_rel(f"{src_dir}/{sub}"))
                tried: list[str] = []
                for entry in ("index", "src/index"):
                    r = self._resolve_base(_norm_rel(f"{src_dir}/{entry}"))
                    if r.kind == "file":
                        return r
                    tried.extend(r.candidates)
                return ResolvedModule("missing", candidates=tried,
                                      note=f"workspace package {pkg} has no index module under {src_dir}")
        return ResolvedModule("external", note="bare specifier; not a path in this repository")

    def _resolve_base(self, base: str) -> ResolvedModule:
        candidates = [_norm_rel(c) for c in self._module_candidates(base)]
        incomplete: list[str] = []
        for cand in candidates:
            if self._paths.has_entry(cand):
                return ResolvedModule("file", file=cand, candidates=candidates)
            reason = self._paths.outside_index(cand)
            if reason:
                incomplete.append(f"{cand}: {reason}")
        if incomplete:
            return ResolvedModule("unindexed", candidates=candidates, note="; ".join(incomplete))
        # A generated module is gitignored and absent from a bare checkout, so
        # the index never covered it. The plugin ranks candidates source-first:
        # when the source form itself is ignored the module is generated and
        # its absence says nothing; when only artefact forms (`.js`, `.d.ts`)
        # are ignored they would be emitted from the missing source, so the
        # miss stands, at reduced confidence, with the ignored forms named.
        # Asked of git only on a miss, so this stays cheap.
        ignored = set(self._paths.gitignored(candidates))
        if candidates and candidates[0] in ignored:
            return ResolvedModule("unindexed", candidates=candidates,
                                  note=f"{candidates[0]} is gitignored (generated); absence cannot be established")
        note = (f"artefact forms are gitignored ({', '.join(c for c in candidates if c in ignored)}); "
                f"the source form {candidates[0]} is not, and is absent") if ignored and candidates else ""
        return ResolvedModule("missing", candidates=candidates, note=note)

    # -- binding -------------------------------------------------------------

    def import_of(self, from_file: str, local_name: str) -> dict | None:
        for imp in self._structure.get(from_file, {}).get("imports", []):
            if imp.get("reexport"):
                continue
            if local_name in imp.get("names", []):
                return imp
        return None

    def lookup_export(self, file: str, name: str, seen: set[tuple[str, str]] | None = None) -> Declaration | None:
        """The declaration ``file`` exports as ``name``, following re-exports."""
        seen = seen if seen is not None else set()
        if (file, name) in seen:
            return None
        seen.add((file, name))
        facts = self._structure.get(file)
        if facts is None:
            return None
        aliases = {e.get("alias"): e["name"] for e in facts.get("local_exports", []) if e.get("alias")}
        local_name = aliases.get(name, name)
        for decl in self._decls.get(file, []):
            if decl.name == local_name and decl.exported:
                return decl
        for imp in facts.get("imports", []):
            if not imp.get("reexport"):
                continue
            target = self.resolve_specifier(file, imp["specifier"])
            if target.kind != "file" or not target.file:
                continue
            if imp.get("star"):
                found = self.lookup_export(target.file, name, seen)
                if found is not None:
                    return found
            elif name in imp.get("names", []):
                original = (imp.get("name_map") or {}).get(name, name)
                found = self.lookup_export(target.file, original, seen)
                if found is not None:
                    return found
        return None

    def bind(self, from_file: str, local_name: str) -> tuple[Declaration | None, str]:
        """Resolve a local identifier to its declaration; the note explains a None.

        Same-file top-level declarations win; otherwise the import that binds
        the name is followed to the exporting file through re-exports.
        """
        for decl in self._decls.get(from_file, []):
            if decl.name == local_name:
                return decl, ""
        imp = self.import_of(from_file, local_name)
        if imp is None:
            return None, f"`{local_name}` is neither declared in the file nor imported"
        if imp.get("namespace") == local_name:
            return None, f"`{local_name}` is a namespace import"
        if imp.get("default") == local_name:
            return None, f"`{local_name}` is a default import"
        target = self.resolve_specifier(from_file, imp["specifier"])
        if target.kind != "file" or not target.file:
            return None, f"`{local_name}` comes from `{imp['specifier']}` ({target.kind}: {target.note or 'not in the tree'})"
        original = (imp.get("name_map") or {}).get(local_name, local_name)
        decl = self.lookup_export(target.file, original)
        if decl is None:
            return None, f"`{original}` is not exported by {target.file} (re-export chain followed)"
        return decl, ""

    def resolve_type(self, from_file: str, name: str) -> tuple[Declaration | None, str]:
        decl, note = self.bind(from_file, name)
        if decl is not None and decl.kind not in _TYPE_KINDS:
            return None, f"`{name}` binds to a {decl.kind}, not a type"
        return decl, note

    # -- member sets ---------------------------------------------------------

    def member_set(self, decl: Declaration, seen: set[tuple[str, str]] | None = None) -> tuple[dict[str, dict], bool, list[str]]:
        """Members walking ``extends``: (members by name, open, unresolved bases).

        ``open`` is True when any part of the chain admits members the
        registry cannot list (an index signature, a spread, a computed key);
        ``unresolved`` names the bases that could not be followed inside the
        repository.
        """
        seen = seen if seen is not None else set()
        key = (decl.file, decl.name)
        if key in seen:
            return {}, False, []
        seen.add(key)
        members: dict[str, dict] = {}
        for m in decl.members or []:
            members.setdefault(m["name"], m)
        open_ = decl.open or decl.members is None
        unresolved: list[str] = []
        for base_name in decl.extends:
            base, _ = self.resolve_type(decl.file, base_name)
            if base is None:
                unresolved.append(base_name)
                continue
            b_members, b_open, b_unresolved = self.member_set(base, seen)
            for name, m in b_members.items():
                members.setdefault(name, m)
            open_ = open_ or b_open
            unresolved.extend(b_unresolved)
        return members, open_, unresolved

    def param_member_set(self, from_file: str, param: dict) -> tuple[dict[str, dict] | None, str]:
        """Closed member set of a parameter's declared type, or (None, why not)."""
        if param.get("rest"):
            return None, "rest parameter"
        if param.get("open"):
            return None, "parameter type is not a closed member set"
        refs = ([param["type"]] if param.get("type") else []) + list(param.get("intersection") or [])
        if not refs and param.get("members") is None:
            return None, "parameter has no declared type"
        members: dict[str, dict] = {}
        for ref in refs:
            decl, note = self.resolve_type(from_file, ref)
            if decl is None:
                return None, note or f"type `{ref}` does not resolve in the repository"
            if decl.kind not in ("interface", "type"):
                return None, f"`{ref}` is a {decl.kind}, not a member set"
            m, open_, unresolved = self.member_set(decl)
            if open_ or unresolved:
                return None, f"`{ref}` is open or extends something outside the repository ({', '.join(unresolved) or 'index signature'})"
            members.update(m)
        for name in param.get("members") or []:
            members.setdefault(name, {"name": name})
        return members, ""

    # -- duplicates ----------------------------------------------------------

    def duplicate_groups(self) -> list[list[Declaration]]:
        groups: list[list[Declaration]] = []
        for (name, kind), decls in self._by_name.items():
            if kind not in _TYPE_KINDS:
                continue
            exported = [d for d in decls if d.exported]
            if len({d.file for d in exported}) >= 2:
                groups.append(sorted(exported, key=lambda d: (d.file, d.line)))
        return groups
