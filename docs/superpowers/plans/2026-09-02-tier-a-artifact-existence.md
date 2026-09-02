# Tier A: Mechanical Artifact-Existence Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a zero-LLM audit layer that extracts literal artifact claims from documentation (a script name a doc tells you to run, a path a doc names) and verifies each against a closed-world registry built mechanically from the repository, emitting reviewer-checkable evidence packets.

**Architecture:** Two mechanical registries (`PathRegistry`, `ScriptRegistry`) are built from the walker's file list and the repo's manifests. A markdown claim extractor turns backticked commands and paths into typed `DocClaim`s. A verifier compares claims to registries and returns `EvidencePacket`s with a deterministic verdict (`contradicted` / `supported` / `undecidable`), the namespace searched, and near matches. Packets become `AuditIssue`s (category `doc_nonexistent_artifact`) in the audit and are exposed by a new `osoji claims` command. A replay script scores the layer against the pre-sweep inventory so the class-level recall is measurable before anything else is built.

**Tech Stack:** Python 3.11+, dataclasses, `re`, `difflib`, `json`, `tomllib` (stdlib), pytest with the `temp_dir` fixture. No new dependencies. No LLM calls anywhere in this plan.

**Spec:** osojicode/wiki `decisions/0031-mechanical-truth-layer-and-claim-compiler.md` (design) and `sources/0005-mcp-debugger-docs-sweep-comparison.md` (the measured failure this plan attacks: 25 of 28 `nonexistent_artifact` corrections missed, plus `wrong_path` 10, `wrong_command` 4, `stale_pointer` 11).

## Global Constraints

- Language agnosticism is non-negotiable: registries are driven by ecosystem manifests found in the tree (`package.json`, `Makefile`, `pyproject.toml`), never by assumptions about one language. Adding an ecosystem is adding one parser function, not touching the extractor or verifier.
- Zero LLM calls in this layer. Every verdict is reproducible from the checkout alone.
- Never emit `contradicted` against an empty or absent namespace (decision 0016's truncation veto): if no manifest of the relevant ecosystem exists, the claim is `undecidable`.
- Placeholders are rejected by principle, not by catalog: a token containing `<`, `>`, `{`, `}`, `$`, `*`, `...`, or a segment named `path`/`to`/`your` is not a literal claim.
- Findings follow the existing product boundary: `AuditIssue` with `origin={"source": "static", "plugin": "tier_a"}`, a new `exclude_key="doc-claims"`, severity `error` for a contradicted command or path (commission).
- Type hints throughout; tests use the `temp_dir` fixture and `Config(root_path=temp_dir, respect_gitignore=False)`; commits in imperative mood.
- Do not touch `src/osoji/**` while an `osoji audit` is running from this checkout (the editable install imports lazily). Check `tasklist | findstr python` or the session log before starting Task 1.
- Branch: `git checkout -b tier-a-artifact-claims` from `main`. One PR at the end; JF merges.

---

### Task 1: Path registry

**Files:**
- Create: `src/osoji/factreg.py`
- Test: `tests/test_factreg.py`

**Interfaces:**
- Consumes: `osoji.walker.list_repo_files(config) -> tuple[Iterable[Path], bool]` (absolute or root-relative paths respecting ignores), `osoji.config.Config` (`root_path`).
- Produces: `Location(path: str, line: int | None)`, `RegistryAnswer(name: str, found: bool, locations: list[Location], near: list[str], namespace: str, searched: list[str], complete: bool)`, `PathRegistry.from_config(config) -> PathRegistry`, `PathRegistry.exists(rel_path: str) -> RegistryAnswer`, `PathRegistry.size -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_factreg.py
"""Tests for the mechanical fact registries (Tier A)."""

from pathlib import Path

from osoji.config import Config
from osoji.factreg import PathRegistry


def _repo(temp_dir: Path, files: dict[str, str]) -> Config:
    for rel, content in files.items():
        p = temp_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Config(root_path=temp_dir, respect_gitignore=False)


def test_path_registry_finds_tracked_file_and_its_directories(temp_dir):
    config = _repo(temp_dir, {"src/app/main.ts": "export {}\n", "README.md": "# x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("src/app/main.ts").found is True
    assert reg.exists("src/app").found is True
    assert reg.exists("src").found is True
    assert reg.exists("README.md").found is True


def test_path_registry_normalizes_separators_and_leading_dot_slash(temp_dir):
    config = _repo(temp_dir, {"docs/guide.md": "x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("./docs/guide.md").found is True
    assert reg.exists("docs\\guide.md").found is True
    assert reg.exists("docs/guide.md/").found is True


def test_path_registry_reports_absence_with_near_matches(temp_dir):
    config = _repo(temp_dir, {"scripts/check-docs.mjs": "x\n", "scripts/check-deps.mjs": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("scripts/check-doc.mjs")
    assert answer.found is False
    assert answer.namespace == "paths"
    assert answer.complete is True
    assert "scripts/check-docs.mjs" in answer.near
    assert answer.locations == []


def test_path_registry_marks_ignored_paths_absent(temp_dir):
    config = _repo(temp_dir, {"node_modules/x/index.js": "x\n", "src/a.ts": "x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("node_modules/x/index.js").found is False
    assert reg.size >= 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_factreg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'osoji.factreg'`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/osoji/factreg.py
"""Mechanical fact registries (Tier A of decisions/0031).

A registry answers closed-world questions about the checkout — "does this
path exist", "is this script declared" — from parsers, never from LLM text.
Every answer carries the namespace that was searched and the near matches, so
absence is an auditable query rather than a retrieval miss.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .walker import list_repo_files


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

    def __init__(self, entries: set[str]):
        self._entries = entries
        self._sorted = sorted(entries)

    @classmethod
    def from_config(cls, config: Config) -> "PathRegistry":
        entries: set[str] = set()
        paths, _used_git = list_repo_files(config)
        for path in paths:
            p = path if path.is_absolute() else config.root_path / path
            try:
                rel = _norm_rel(str(p.relative_to(config.root_path)))
            except ValueError:
                continue
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_factreg.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/osoji/factreg.py tests/test_factreg.py
git commit -m "Add PathRegistry: closed-world path existence from the walker"
```

---

### Task 2: Script registry from manifests

**Files:**
- Modify: `src/osoji/factreg.py` (append)
- Test: `tests/test_factreg.py` (append)

**Interfaces:**
- Consumes: `osoji.junk_cicd._parse_makefile(content: str, path: str) -> list[CICDElement]` (`element_type == "makefile_target"`, `element_name`, `line_start`), `PathRegistry`, `Location`, `RegistryAnswer`, `_near`.
- Produces: `ScriptRegistry.from_config(config) -> ScriptRegistry`, `ScriptRegistry.exists(name: str, ecosystem: str | None = None) -> RegistryAnswer`, `ScriptRegistry.manifests -> list[str]`. Ecosystems: `"npm"` (package.json scripts, any package.json in the tree), `"make"` (Makefile targets), `"python"` (pyproject `[project.scripts]`). Namespace string is `"scripts"`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_factreg.py
import json
import textwrap

from osoji.factreg import ScriptRegistry


def test_script_registry_reads_package_json_scripts_across_workspaces(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"name": "root", "scripts": {"build": "tsc -b", "test:unit": "vitest run"}}),
        "packages/api/package.json": json.dumps({"name": "api", "scripts": {"dev:server": "node dist/server.js"}}),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("test:unit", "npm").found is True
    assert reg.exists("dev:server", "npm").found is True
    assert reg.exists("test:unit", "npm").locations[0].path == "package.json"
    assert sorted(reg.manifests) == ["package.json", "packages/api/package.json"]


def test_script_registry_absent_script_reports_near_matches_and_namespace(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"scripts": {"test": "vitest", "test:unit": "vitest run", "test:e2e": "playwright"}}),
    })
    reg = ScriptRegistry.from_config(config)

    answer = reg.exists("test:ui", "npm")
    assert answer.found is False
    assert answer.complete is True
    assert answer.namespace == "scripts"
    assert answer.searched == ["package.json#scripts"]
    assert "test:unit" in answer.near


def test_script_registry_reads_makefile_targets_and_pyproject_scripts(temp_dir):
    config = _repo(temp_dir, {
        "Makefile": textwrap.dedent("""\
            .PHONY: lint
            lint:
            \truff check .
            build: lint
            \tpython -m build
            """),
        "pyproject.toml": textwrap.dedent("""\
            [project]
            name = "demo"
            [project.scripts]
            demo-cli = "demo.cli:main"
            """),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("lint", "make").found is True
    assert reg.exists("build", "make").found is True
    assert reg.exists("demo-cli", "python").found is True
    assert reg.exists("deploy", "make").found is False


def test_script_registry_is_undecidable_when_no_manifest_of_that_ecosystem_exists(temp_dir):
    config = _repo(temp_dir, {"README.md": "# no manifests\n"})
    reg = ScriptRegistry.from_config(config)

    answer = reg.exists("build", "npm")
    assert answer.found is False
    assert answer.complete is False
    assert answer.searched == []


def test_script_registry_any_ecosystem_lookup(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"scripts": {"build": "tsc"}}),
        "Makefile": "test:\n\tpytest\n",
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("build").found is True
    assert reg.exists("test").found is True
    assert reg.exists("nope").found is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_factreg.py -v -k script_registry`
Expected: FAIL with `ImportError: cannot import name 'ScriptRegistry'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to src/osoji/factreg.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_factreg.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/osoji/factreg.py tests/test_factreg.py
git commit -m "Add ScriptRegistry: declared runnable names from package.json, Makefile, pyproject"
```

---

### Task 3: Markdown claim extractor

**Files:**
- Create: `src/osoji/claims_docs.py`
- Test: `tests/test_claims_docs.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure text → claims).
- Produces: `DocClaim(kind: str, name: str, doc_path: str, line: int, text: str, ecosystem: str | None, in_fence: bool)` with `kind in {"script_exists", "path_exists"}`; `extract_doc_claims(doc_path: str, content: str) -> list[DocClaim]`; helper `is_placeholder(token: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_claims_docs.py
"""Tests for mechanical claim extraction from markdown (Tier A)."""

import textwrap

from osoji.claims_docs import DocClaim, extract_doc_claims, is_placeholder


def _claims(md: str) -> list[DocClaim]:
    return extract_doc_claims("docs/guide.md", textwrap.dedent(md))


def test_extracts_npm_and_pnpm_script_claims_with_ecosystem():
    claims = _claims("""\
        Build with `npm run build:packages`, then run `pnpm run test:ui`.

        ```bash
        pnpm test:e2e
        yarn lint
        ```
        """)
    scripts = [(c.name, c.ecosystem, c.in_fence, c.line) for c in claims if c.kind == "script_exists"]
    assert ("build:packages", "npm", False, 1) in scripts
    assert ("test:ui", "npm", False, 1) in scripts
    assert ("test:e2e", "npm", True, 4) in scripts
    assert ("lint", "npm", True, 5) in scripts


def test_package_manager_builtins_are_not_script_claims():
    claims = _claims("Run `npm install` then `pnpm install --frozen-lockfile` and `npm ci`.\n")
    assert [c for c in claims if c.kind == "script_exists"] == []


def test_extracts_make_targets():
    claims = _claims("Type `make docker-e2e` to run the suite.\n")
    assert [(c.name, c.ecosystem) for c in claims if c.kind == "script_exists"] == [("docker-e2e", "make")]


def test_extracts_repo_relative_path_claims_from_backticks():
    claims = _claims("""\
        See `src/server/tool-schemas.ts` and the `docs/architecture/` folder.
        The entry point is `packages/mcp-debugger/dist/index.js`.
        """)
    paths = sorted(c.name for c in claims if c.kind == "path_exists")
    assert paths == ["docs/architecture", "packages/mcp-debugger/dist/index.js", "src/server/tool-schemas.ts"]


def test_rejects_placeholders_urls_absolute_and_bare_words():
    claims = _claims("""\
        Use `path/to/your/file.ts` or `<project>/src/x.ts` or `src/**/*.ts` or `${ROOT}/a.ts`.
        Open `https://example.com/docs/x.md` or `/usr/local/bin/node` or `C:\\Users\\me\\a.ts`.
        Call `initialize` and pass `--stdio`.
        """)
    assert claims == []
    assert is_placeholder("path/to/file") is True
    assert is_placeholder("src/a.ts") is False


def test_claim_carries_source_span_and_text():
    claims = _claims("Edit `packages/shared/README.md` first.\n")
    (claim,) = claims
    assert claim.doc_path == "docs/guide.md"
    assert claim.line == 1
    assert claim.text == "packages/shared/README.md"
    assert claim.in_fence is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_claims_docs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'osoji.claims_docs'`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/osoji/claims_docs.py
"""Mechanical claim extraction from markdown (Tier A of decisions/0031).

Only literal, checkable claims are extracted here: a script a doc tells the
reader to run, a repo-relative path a doc names. Anything that reads as a
placeholder, URL, absolute path, glob or shell expansion is not a claim.
Prose claims that need judgement (behaviour, signatures, counts) are Tier B
and are not this module's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `npm run x`, `pnpm run x`, `yarn run x`, `pnpm x`, `yarn x`, `npm test|start`
_SCRIPT_RE = re.compile(
    r"\b(?P<pm>npm|pnpm|yarn)\s+(?:run\s+(?P<run>[\w:.\-]+)|(?P<bare>[\w:.\-]+))"
)
_MAKE_RE = re.compile(r"\bmake\s+(?P<target>[A-Za-z_][\w.\-]*)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Package-manager verbs that are never project scripts. Principle: a bare
# `pm <word>` is a script claim only when the word is not a verb the package
# manager itself defines; npm's `test`/`start` are script aliases.
_PM_BUILTINS = {
    "install", "i", "ci", "add", "remove", "rm", "uninstall", "update", "upgrade",
    "link", "unlink", "publish", "pack", "init", "exec", "dlx", "create", "cache",
    "config", "audit", "outdated", "why", "ls", "list", "info", "view", "login",
    "logout", "whoami", "version", "help", "run", "workspace", "workspaces", "dedupe",
    "prune", "rebuild", "store", "setup", "import", "patch", "fetch", "env", "up",
}
_NPM_SCRIPT_ALIASES = {"test", "start", "stop", "restart"}

_PLACEHOLDER_SEGMENTS = {"path", "to", "your", "my", "some", "example", "foo", "bar"}


@dataclass(frozen=True)
class DocClaim:
    kind: str                # "script_exists" | "path_exists"
    name: str                # the script name or normalized relative path
    doc_path: str
    line: int                # 1-based
    text: str                # the literal token as written
    ecosystem: str | None    # "npm" | "make" | None
    in_fence: bool


def is_placeholder(token: str) -> bool:
    if any(ch in token for ch in "<>{}$*"):
        return True
    if "..." in token:
        return True
    segments = [s.lower() for s in token.replace("\\", "/").split("/")]
    return any(seg in _PLACEHOLDER_SEGMENTS for seg in segments)


def _looks_like_repo_path(token: str) -> bool:
    t = token.strip()
    if not t or is_placeholder(t):
        return False
    if "://" in t or t.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:[\\/]", t):
        return False
    if t.startswith("-") or " " in t:
        return False
    # A separator is required. Bare `name.ext` tokens are ambiguous with dotted
    # identifiers (`process.env`, `Client.close`) and would produce false
    # "nonexistent path" findings; they are left to a later, registry-aware
    # extraction. Losing `README.md`-style bare claims costs little recall.
    return "/" in t


def _norm_path(token: str) -> str:
    s = token.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.rstrip("/")


def extract_doc_claims(doc_path: str, content: str) -> list[DocClaim]:
    claims: list[DocClaim] = []
    seen: set[tuple[str, str, int]] = set()
    in_fence = False

    def add(kind: str, name: str, line: int, text: str, eco: str | None) -> None:
        key = (kind, name, line)
        if key in seen:
            return
        seen.add(key)
        claims.append(DocClaim(kind, name, doc_path, line, text, eco, in_fence))

    for i, raw in enumerate(content.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        line = raw
        for m in _SCRIPT_RE.finditer(line):
            name = m.group("run") or m.group("bare")
            if m.group("bare") and (name in _PM_BUILTINS or (m.group("pm") == "npm" and name not in _NPM_SCRIPT_ALIASES)):
                continue
            if name in _PM_BUILTINS:
                continue
            add("script_exists", name, i, name, "npm")
        for m in _MAKE_RE.finditer(line):
            add("script_exists", m.group("target"), i, m.group("target"), "make")
        for m in _BACKTICK_RE.finditer(line):
            token = m.group(1).strip()
            if _SCRIPT_RE.search(token) or _MAKE_RE.search(token):
                continue  # already handled as a command
            if _looks_like_repo_path(token):
                add("path_exists", _norm_path(token), i, token, None)
    return claims
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_claims_docs.py -v`
Expected: 6 passed. If `test_extracts_npm_and_pnpm_script_claims_with_ecosystem` fails on `("lint", "npm", True, 5)`, the bare-word rule is wrong: `yarn lint` and `pnpm test:e2e` must count (bare word, not a builtin) while `npm <bare>` counts only for the aliases. Fix the condition, do not loosen the test.

- [ ] **Step 5: Commit**

```bash
git add src/osoji/claims_docs.py tests/test_claims_docs.py
git commit -m "Add markdown claim extractor for script and path existence claims"
```

---

### Task 4: Verifier and evidence packets

**Files:**
- Create: `src/osoji/tier_a.py`
- Test: `tests/test_tier_a.py`

**Interfaces:**
- Consumes: `DocClaim`, `PathRegistry`, `ScriptRegistry`, `RegistryAnswer`, `Location`.
- Produces: `EvidencePacket(claim: DocClaim, verdict: str, namespace: str, searched: list[str], locations: list[Location], near: list[str], index_revision: str, note: str)` with `verdict in {"contradicted", "supported", "undecidable"}`; `verify_doc_claims(claims: list[DocClaim], paths: PathRegistry, scripts: ScriptRegistry, index_revision: str = "") -> list[EvidencePacket]`; `packet_message(p: EvidencePacket) -> str` and `packet_remediation(p: EvidencePacket) -> str`; `EvidencePacket.to_dict() -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tier_a.py
"""Tests for the Tier A deterministic verifier."""

import json

from osoji.claims_docs import DocClaim
from osoji.config import Config
from osoji.factreg import PathRegistry, ScriptRegistry
from osoji.tier_a import EvidencePacket, packet_message, verify_doc_claims


def _setup(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "test:unit": "vitest run"}}), encoding="utf-8")
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "server.ts").write_text("export {}\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    return PathRegistry.from_config(config), ScriptRegistry.from_config(config)


def _claim(kind, name, eco=None):
    return DocClaim(kind=kind, name=name, doc_path="README.md", line=7, text=name, ecosystem=eco, in_fence=False)


def test_missing_script_is_contradicted_with_namespace_and_near_matches(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("script_exists", "test:ui", "npm")], paths, scripts, index_revision="abc123")

    assert packet.verdict == "contradicted"
    assert packet.namespace == "scripts"
    assert packet.searched == ["package.json#scripts"]
    assert "test:unit" in packet.near
    assert packet.index_revision == "abc123"
    msg = packet_message(packet)
    assert "test:ui" in msg and "package.json#scripts" in msg and "test:unit" in msg


def test_present_script_and_path_are_supported_with_locations(temp_dir):
    paths, scripts = _setup(temp_dir)
    packets = verify_doc_claims(
        [_claim("script_exists", "test:unit", "npm"), _claim("path_exists", "src/server.ts")], paths, scripts
    )
    assert [p.verdict for p in packets] == ["supported", "supported"]
    assert packets[0].locations[0].path == "package.json"
    assert packets[1].locations[0].path == "src/server.ts"


def test_missing_path_is_contradicted(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("path_exists", "src/servr.ts")], paths, scripts)
    assert packet.verdict == "contradicted"
    assert "src/server.ts" in packet.near


def test_script_claim_without_manifest_is_undecidable(temp_dir):
    (temp_dir / "README.md").write_text("x\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)
    (packet,) = verify_doc_claims([_claim("script_exists", "build", "npm")], paths, scripts)
    assert packet.verdict == "undecidable"
    assert packet.searched == []


def test_packet_serializes_to_plain_dict(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("script_exists", "test:ui", "npm")], paths, scripts)
    d = packet.to_dict()
    assert d["claim"]["name"] == "test:ui" and d["verdict"] == "contradicted"
    assert isinstance(d["searched"], list) and isinstance(d["near"], list)
    json.dumps(d)  # must be JSON-serializable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_tier_a.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'osoji.tier_a'`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/osoji/tier_a.py
"""Tier A verifier: deterministic verdicts for mechanical doc claims.

A packet is the finding's evidence: the claim, what namespace was searched,
what was found, and the nearest declared names when nothing was. No LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .claims_docs import DocClaim
from .factreg import Location, PathRegistry, RegistryAnswer, ScriptRegistry


@dataclass
class EvidencePacket:
    claim: DocClaim
    verdict: str                     # "contradicted" | "supported" | "undecidable"
    namespace: str
    searched: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    index_revision: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claim"] = asdict(self.claim)
        d["locations"] = [asdict(l) for l in self.locations]
        return d


def _verdict(answer: RegistryAnswer) -> str:
    if not answer.complete:
        return "undecidable"
    return "supported" if answer.found else "contradicted"


def verify_doc_claims(
    claims: list[DocClaim],
    paths: PathRegistry,
    scripts: ScriptRegistry,
    index_revision: str = "",
) -> list[EvidencePacket]:
    packets: list[EvidencePacket] = []
    for claim in claims:
        if claim.kind == "script_exists":
            answer = scripts.exists(claim.name, claim.ecosystem)
        elif claim.kind == "path_exists":
            answer = paths.exists(claim.name)
        else:
            continue
        note = "" if answer.complete else "no manifest of this ecosystem in the tree; absence cannot be established"
        packets.append(EvidencePacket(
            claim=claim, verdict=_verdict(answer), namespace=answer.namespace,
            searched=list(answer.searched), locations=list(answer.locations),
            near=list(answer.near), index_revision=index_revision, note=note,
        ))
    return packets


def packet_message(p: EvidencePacket) -> str:
    what = "script" if p.claim.kind == "script_exists" else "path"
    if p.verdict == "contradicted":
        near = f"; nearest declared: {', '.join(p.near)}" if p.near else ""
        return (f"Doc names {what} `{p.claim.text}` but it is not declared in the checkout "
                f"(searched {', '.join(p.searched)}{near})")
    if p.verdict == "supported":
        where = ", ".join(f"{l.path}:{l.line}" if l.line else l.path for l in p.locations)
        return f"Doc names {what} `{p.claim.text}`; declared at {where}"
    return f"Doc names {what} `{p.claim.text}`; {p.note}"


def packet_remediation(p: EvidencePacket) -> str:
    if p.verdict != "contradicted":
        return ""
    if p.near:
        return f"Replace `{p.claim.text}` with the declared name (nearest: {p.near[0]}), or declare it."
    return f"Declare `{p.claim.text}` or remove the reference from the doc."
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_tier_a.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/osoji/tier_a.py tests/test_tier_a.py
git commit -m "Add Tier A verifier: deterministic evidence packets for doc claims"
```

---

### Task 5: `osoji claims` command and audit wiring

**Files:**
- Modify: `src/osoji/cli.py` (add a command after `verify`, around line 463-520)
- Modify: `src/osoji/audit.py:83` (`EXCLUDABLE_PHASES`), `src/osoji/audit.py:556` (issue collection, add a Phase 2a block before "Collect issues from Phase 2")
- Modify: `src/osoji/config.py:792` (add `analysis_claims_path_for`)
- Test: `tests/test_tier_a_cli.py`, `tests/test_audit_tier_a.py`

**Interfaces:**
- Consumes: `extract_doc_claims`, `verify_doc_claims`, `PathRegistry`, `ScriptRegistry`, `packet_message`, `packet_remediation`, `EvidencePacket.to_dict`, `osoji.doc_analysis.find_doc_candidates(config) -> list[Path]`, `AuditIssue`, `_serialize_json(path, data)`.
- Produces: `osoji.tier_a.run_tier_a(config) -> list[EvidencePacket]` (discovers docs, extracts, verifies; `index_revision` = current git HEAD short sha or `""`), CLI `osoji claims [PATH] --format text|json [--all]` (default prints contradicted packets only; `--all` prints every packet; exit code 1 when any contradicted), audit issues with `category="doc_nonexistent_artifact"`, `severity="error"`, `origin={"source": "static", "plugin": "tier_a"}`, `exclude_key="doc-claims"`, and `.osoji/analysis/claims/<doc>.claims.json` per doc.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tier_a_cli.py
"""osoji claims: zero-LLM Tier A entry point."""

import json

from click.testing import CliRunner

from osoji.cli import main


def _repo(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "docs").mkdir()
    (temp_dir / "docs" / "guide.md").write_text(
        "Run `npm run build` then `npm run test:ui`. See `src/missing.ts`.\n", encoding="utf-8"
    )


def test_claims_text_reports_contradicted_and_exits_1(temp_dir):
    _repo(temp_dir)
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--no-gitignore"])
    assert result.exit_code == 1, result.output
    assert "test:ui" in result.output and "src/missing.ts" in result.output
    assert "npm run build" not in result.output  # supported claims hidden by default


def test_claims_json_all_lists_every_packet(temp_dir):
    _repo(temp_dir)
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--format", "json", "--all", "--no-gitignore"])
    data = json.loads(result.output)
    verdicts = sorted(p["verdict"] for p in data["packets"])
    assert verdicts == ["contradicted", "contradicted", "supported"]
    assert data["summary"]["contradicted"] == 2


def test_claims_clean_repo_exits_0(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text("Run `npm run build`.\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--no-gitignore"])
    assert result.exit_code == 0, result.output
```

```python
# tests/test_audit_tier_a.py
"""Tier A issues reach the audit result without any LLM call."""

import json
from pathlib import Path

from osoji.audit import AuditIssue, tier_a_issues
from osoji.config import Config


def test_tier_a_issues_from_config(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text("Run `npm run test:ui`.\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)

    issues, packets = tier_a_issues(config)

    (issue,) = issues
    assert isinstance(issue, AuditIssue)
    assert issue.category == "doc_nonexistent_artifact"
    assert issue.severity == "error"
    assert issue.exclude_key == "doc-claims"
    assert issue.origin == {"source": "static", "plugin": "tier_a"}
    assert issue.line_start == 1
    assert Path(issue.path).name == "README.md"
    assert "test:ui" in issue.message and "package.json#scripts" in issue.message
    assert len(packets) == 1
    assert (config.analysis_root / "claims" / "README.md.claims.json").exists()


def test_tier_a_respects_exclude(temp_dir):
    (temp_dir / "README.md").write_text("See `src/nope.ts`.\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    issues, packets = tier_a_issues(config, exclude={"doc-claims"})
    assert issues == [] and packets == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_tier_a_cli.py tests/test_audit_tier_a.py -v`
Expected: FAIL (`No such command 'claims'`; `ImportError: cannot import name 'tier_a_issues'`)

- [ ] **Step 3: Write the implementation**

Append to `src/osoji/tier_a.py`:

```python
import subprocess
from pathlib import Path

from .config import Config


def _index_revision(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_tier_a(config: Config) -> list[EvidencePacket]:
    """Discover docs, extract literal claims, verify against the registries."""
    from .claims_docs import extract_doc_claims
    from .doc_analysis import find_doc_candidates

    paths = PathRegistry.from_config(config)
    scripts = ScriptRegistry.from_config(config)
    rev = _index_revision(config.root_path)
    packets: list[EvidencePacket] = []
    for doc in find_doc_candidates(config):
        try:
            content = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(doc.relative_to(config.root_path)).replace("\\", "/")
        claims = extract_doc_claims(rel, content)
        packets.extend(verify_doc_claims(claims, paths, scripts, index_revision=rev))
    return packets
```

Add to `src/osoji/config.py` next to `analysis_docs_path_for`:

```python
    def analysis_claims_path_for(self, doc_path: Path) -> Path:
        """Return the Tier A evidence-packet JSON path for a given doc file."""

        relative = self._to_relative(doc_path)
        return self.analysis_root / "claims" / (str(relative) + ".claims.json")
```

Add to `src/osoji/audit.py`: `"doc-claims"` in `EXCLUDABLE_PHASES` (line 83 list, after `"doc-analysis"`), and this function above `run_audit`:

```python
def tier_a_issues(config: Config, exclude: set[str] | None = None) -> tuple[list[AuditIssue], list["EvidencePacket"]]:
    """Phase 2a: mechanical doc-claim verification (decisions/0031 Tier A). Zero LLM."""
    from .tier_a import packet_message, packet_remediation, run_tier_a

    if exclude and "doc-claims" in exclude:
        return [], []
    packets = run_tier_a(config)
    by_doc: dict[str, list] = {}
    for p in packets:
        by_doc.setdefault(p.claim.doc_path, []).append(p)
    for doc, doc_packets in by_doc.items():
        _serialize_json(config.analysis_claims_path_for(config.root_path / doc),
                        {"doc": doc, "packets": [p.to_dict() for p in doc_packets]})
    issues = [
        AuditIssue(
            path=config.root_path / p.claim.doc_path,
            severity="error",
            category="doc_nonexistent_artifact",
            message=packet_message(p),
            remediation=packet_remediation(p),
            line_start=p.claim.line,
            line_end=p.claim.line,
            origin={"source": "static", "plugin": "tier_a"},
            exclude_key="doc-claims",
            verdict="confirmed",
            confidence=1.0,
            triage_reasoning=f"Deterministic: {p.namespace} namespace searched ({', '.join(p.searched)}); index {p.index_revision}",
        )
        for p in packets if p.verdict == "contradicted"
    ]
    return issues, packets
```

Wire it in `run_audit_async` immediately before the line `# Collect issues from Phase 2 (doc analysis)`:

```python
    # Phase 2a: mechanical doc claims (Tier A, zero LLM)
    tier_a_start = time_module.monotonic()
    tier_a_list, _tier_a_packets = tier_a_issues(config, exclude=_exclude)
    issues.extend(tier_a_list)
    _emit(config, f"  [phase 2a doc claims: {time_module.monotonic() - tier_a_start:.1f}s] {len(tier_a_list)} contradicted")
```

Add the CLI command to `src/osoji/cli.py` after `verify`:

```python
@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--all", "show_all", is_flag=True, help="Show supported and undecidable claims too")
@click.option("--no-gitignore", is_flag=True, help="Do not use git ls-files / .gitignore for discovery")
@click.pass_context
def claims(ctx: click.Context, path: Path, output_format: str, show_all: bool, no_gitignore: bool) -> None:
    """Verify literal doc claims (scripts, paths) against the checkout. No LLM calls."""
    from .tier_a import packet_message, run_tier_a

    state = _cli_state(ctx)
    config = Config(root_path=path.resolve(), respect_gitignore=not no_gitignore, quiet=state.quiet)
    packets = run_tier_a(config)
    contradicted = [p for p in packets if p.verdict == "contradicted"]
    shown = packets if show_all else contradicted
    if output_format == "json":
        summary = {v: sum(1 for p in packets if p.verdict == v) for v in ("contradicted", "supported", "undecidable")}
        click.echo(json.dumps({"packets": [p.to_dict() for p in shown], "summary": summary}, indent=2))
    else:
        for p in shown:
            click.echo(f"{p.claim.doc_path}:{p.claim.line} [{p.verdict}] {packet_message(p)}")
        click.echo(f"{len(contradicted)} contradicted, {len(packets)} claims checked")
    ctx.exit(1 if contradicted else 0)
```

(`json` is already imported in `cli.py`; confirm `_cli_state` and `Config(..., quiet=...)` match the `verify` command's construction at cli.py:479-500 and copy that exact pattern if it differs.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_tier_a_cli.py tests/test_audit_tier_a.py tests/test_audit.py -v`
Expected: all pass. If `test_audit.py` fails because a fixture repo now yields a Tier A issue, the fixture doc names a nonexistent artifact; fix the fixture doc rather than the test.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: pass. `tests/test_skills_parity.py` is unaffected (no skill files changed).

- [ ] **Step 6: Commit**

```bash
git add src/osoji/tier_a.py src/osoji/audit.py src/osoji/cli.py src/osoji/config.py tests/test_tier_a_cli.py tests/test_audit_tier_a.py
git commit -m "Wire Tier A into the audit (phase 2a) and add osoji claims"
```

---

### Task 6: Replay against the pre-sweep inventory (the acceptance gate)

**Files:**
- Create: `scripts/tier_a_replay.py`
- Test: `tests/test_tier_a_replay.py`

**Interfaces:**
- Consumes: `run_tier_a(config)`, the inventory JSONL produced for the honesty test (`runs/mcpdbg-presweep-14610d61/pr643-hunk-inventory.jsonl`, rows with `path`, `partition`, `domain`, `kind`, `claim`, `old_start`).
- Produces: a script that prints per-row hit/miss for rows of the given kinds and a summary `{"rows": n, "hits": h, "recall": h/n}`; pure function `score_rows(rows: list[dict], packets: list[EvidencePacket]) -> list[dict]` for testing. A row is a hit when a `contradicted` packet is on the same doc path and the packet's `claim.name` (case-insensitive) occurs in the row's `claim` text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tier_a_replay.py
import importlib.util
from pathlib import Path

from osoji.claims_docs import DocClaim
from osoji.tier_a import EvidencePacket

_spec = importlib.util.spec_from_file_location("tier_a_replay", Path("scripts/tier_a_replay.py"))
tier_a_replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier_a_replay)


def _packet(doc, name, verdict="contradicted"):
    claim = DocClaim("script_exists", name, doc, 3, name, "npm", False)
    return EvidencePacket(claim=claim, verdict=verdict, namespace="scripts")


def test_score_rows_matches_contradicted_packet_on_same_doc_by_name():
    rows = [
        {"path": "docs/testing-guide.md", "kind": "nonexistent_artifact", "claim": "Old: run `npm run test:ui` — no such script"},
        {"path": "docs/testing-guide.md", "kind": "wrong_path", "claim": "Old: `tests/core/unit/server/server.test.ts` was deleted"},
        {"path": "README.md", "kind": "nonexistent_artifact", "claim": "Old: `registerTools()` does not exist"},
    ]
    packets = [_packet("docs/testing-guide.md", "test:ui"), _packet("README.md", "test:ui", verdict="supported")]
    scored = tier_a_replay.score_rows(rows, packets)
    assert [r["hit"] for r in scored] == [True, False, False]
    assert scored[0]["matched"] == "test:ui"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_tier_a_replay.py -v`
Expected: FAIL with `FileNotFoundError` / `AttributeError: score_rows`

- [ ] **Step 3: Write the script**

```python
# scripts/tier_a_replay.py
"""Score Tier A against a comparator inventory (the honesty-test gate).

Usage:
    python scripts/tier_a_replay.py --repo <checkout> --inventory <rows.jsonl> \
        [--kinds nonexistent_artifact,wrong_path,wrong_command,stale_pointer]

Runs the zero-LLM Tier A layer on the checkout and reports, for every
inventory row of the selected kinds, whether a contradicted packet on the same
doc names the artifact the comparator corrected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from osoji.config import Config  # noqa: E402
from osoji.tier_a import EvidencePacket, run_tier_a  # noqa: E402

DEFAULT_KINDS = "nonexistent_artifact,wrong_path,wrong_command,stale_pointer"


def score_rows(rows: list[dict], packets: list[EvidencePacket]) -> list[dict]:
    by_doc: dict[str, list[EvidencePacket]] = {}
    for p in packets:
        if p.verdict == "contradicted":
            by_doc.setdefault(p.claim.doc_path.replace("\\", "/"), []).append(p)
    out = []
    for r in rows:
        claim_text = (r.get("claim") or "").lower()
        matched = next((p.claim.name for p in by_doc.get(r["path"].replace("\\", "/"), [])
                        if p.claim.name.lower() in claim_text), None)
        out.append({**r, "hit": matched is not None, "matched": matched})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--inventory", required=True, type=Path)
    ap.add_argument("--kinds", default=DEFAULT_KINDS)
    args = ap.parse_args()
    kinds = set(args.kinds.split(","))
    rows = [json.loads(l) for l in args.inventory.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("partition") in ("correction", "deletion")
            and r.get("domain") == "checkout" and r.get("kind") in kinds]
    packets = run_tier_a(Config(root_path=args.repo.resolve()))
    scored = score_rows(rows, packets)
    for r in scored:
        print(f"{'HIT ' if r['hit'] else 'miss'} {r['path']}:{r.get('old_start')} [{r['kind']}] {r.get('claim','')[:110]}")
    hits = sum(1 for r in scored if r["hit"])
    contradicted = sum(1 for p in packets if p.verdict == "contradicted")
    print(json.dumps({"rows": len(scored), "hits": hits, "recall": round(hits / len(scored), 3) if scored else None,
                      "contradicted_packets": contradicted, "claims_checked": len(packets)}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test, then the live replay**

Run: `pytest tests/test_tier_a_replay.py -v` → 1 passed.

Live gate (needs a checkout of mcp-debugger at `14610d61`; the presweep worktree may have moved, so create a fresh one):

```bash
git -C ~/projects/mcp-debugger worktree add ~/projects/mcp-debugger-14610d61 14610d61
python scripts/tier_a_replay.py --repo ~/projects/mcp-debugger-14610d61 --inventory runs/mcpdbg-presweep-14610d61/pr643-hunk-inventory.jsonl
```

Expected: the summary line. **Acceptance for this plan: recall ≥ 0.50 on the 53 rows of the four kinds, and every contradicted packet on a doc the comparator did not touch adjudicated real by reading the doc (precision check by hand on the contradicted list; target ≥ 0.90 for this deterministic class).** Record both numbers in the PR body and in osojicode/wiki `sources/0005` under a "Tier A replay" heading. If recall is under 0.50, inspect the misses by kind: extend the extractor's command grammar or the registry's manifest coverage (one parser function each) before touching anything else.

- [ ] **Step 5: Commit**

```bash
git add scripts/tier_a_replay.py tests/test_tier_a_replay.py
git commit -m "Add Tier A replay against the pre-sweep inventory"
```

---

### Task 7: Docs and product boundary

**Files:**
- Modify: `README.md` ("What it finds" list, ~line 61; "Commands" table, ~line 78)
- Modify: `CLAUDE.md` (Key architecture list: add `tier_a.py`, `factreg.py`, `claims_docs.py`; note the new `claims` subcommand)
- Modify: `src/osoji/osoji-observatory.schema.json` only if the bundle exports the new issue category — it does not in this plan (issues are already free-form `category` strings); verify with `pytest tests/test_observatory.py`.

- [ ] **Step 1: Edit README**

Add to "What it finds": `- **Nonexistent artifacts** — scripts and paths that docs name but the checkout does not declare (zero LLM cost)`.
Add to the command table: `| \`osoji claims .\` | Verify literal doc claims (scripts, paths) against the checkout, no LLM |`.

- [ ] **Step 2: Edit CLAUDE.md**

In the Key architecture list add: `- \`src/osoji/factreg.py\`, \`src/osoji/claims_docs.py\`, \`src/osoji/tier_a.py\` — Tier A: mechanical fact registries (paths, manifest scripts), markdown claim extraction, deterministic verification with evidence packets; runs as audit phase 2a and as \`osoji claims\``.

- [ ] **Step 3: Run the suite and the parity/observatory tests**

Run: `pytest -q`
Expected: pass.

- [ ] **Step 4: Commit and open the PR**

```bash
git add README.md CLAUDE.md
git commit -m "Document Tier A claims verification"
git push -u origin tier-a-artifact-claims
gh pr create --title "Tier A: mechanical doc-claim verification (scripts, paths)" --body "$(cat <<'EOF'
Implements the first slice of osojicode/wiki decisions/0031: zero-LLM verification of literal documentation claims (scripts a doc tells you to run, paths it names) against closed-world registries built from the walker and the repo's manifests. Findings carry the namespace searched and near matches, so absence is an auditable query.

- `factreg.py`: PathRegistry, ScriptRegistry (package.json scripts, Makefile targets, pyproject scripts)
- `claims_docs.py`: markdown claim extractor with principle-based placeholder rejection
- `tier_a.py`: verifier, evidence packets, `run_tier_a`
- audit phase 2a (`doc_nonexistent_artifact`, exclude key `doc-claims`), `osoji claims` command
- `scripts/tier_a_replay.py`: gate against the pre-sweep inventory

Replay at mcp-debugger 14610d61: <rows> rows, <hits> hits, recall <r>; contradicted packets <n>, hand-checked precision <p>.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Do not merge; JF reviews.

---

## Out of scope for this plan (next plans)

- Tier B: LLM claim extraction with modality, member/signature/count checks against the symbol tables (`wrong_signature` 20, `omission_from_list` 14, `wrong_count` 7, `false_statement` 50 of the 156 corrections).
- Claim → fact-key dependency graph and claim-granular incremental re-verification (JF's per-PR cost rule).
- Additional registries: CLI flags/subcommands, env vars, config keys, routes, image tags, enum/registry members.
- Removing shadow docs from the audit's critical path (JF-class product question in 0031).
- Dedup between Tier A and the LLM doc-analysis finding on the same claim.
