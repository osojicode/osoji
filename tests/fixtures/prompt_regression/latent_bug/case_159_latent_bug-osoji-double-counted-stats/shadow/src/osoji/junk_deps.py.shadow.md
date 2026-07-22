# src\osoji\junk_deps.py
@source-hash: 33d1205471a0d039
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:19Z

## Purpose
Dead dependency detection pipeline: discovers manifest files, parses them into `DependencyCandidate` objects, scans source files for imports, uses LLM to resolve import names and classify zero-import candidates, then runs triage to produce `JunkFinding` results.

## Key Classes & Functions

### `DependencyCandidate` (L26-36) — dataclass
Represents a single dependency from a manifest. Fields: `manifest_path`, `package_name`, `import_names`, `import_hits` (default 0), `hit_files`, `is_dev`, `ecosystem`, `line_number`. Mutated in-place by `scan_imports`.

### `DeadDepsAnalyzer` (L758-812) — public, extends `JunkAnalyzer`
Main analyzer class. Implements the `JunkAnalyzer` interface:
- `name` → `"dead_deps"`
- `cli_flag` → `"dead-deps"`
- `analyze(config)` (L773-785): sync wrapper using `asyncio.run`, creates `LLMProvider` via `create_runtime`, calls `analyze_async`
- `analyze_async(provider, config, on_progress=None)` (L787-812): calls `detect_dead_deps_async`, filters to `verdict == "confirmed"`, builds `JunkFinding` list, returns `JunkAnalysisResult`

### `detect_dead_deps_async` (L621-755) — core pipeline, async
Full pipeline orchestrator. Stages:
1. `discover_manifests` → find manifest files at repo root
2. `parse_manifest` → parse each into `DependencyCandidate` list
3. `_resolve_import_names_batch_async` → LLM resolves package→import name (batches of 80)
4. `scan_imports` → regex-scan all source files for import hits
5. `_filter_zero_import` → keep only `import_hits == 0`
6. Pre-filter: remove `_BUILD_TOOLS_CACHE` entries and Node `@types/` packages
7. `_classify_deps_batch_async` → LLM classifies remaining (batches of 50); only `genuine_candidate` classification passes through
8. `finding_from_dep_candidate` + `build_junk_claims` + `decide_junk_claims` → triage pipeline
Returns `(decided_findings, genuine_candidate_count)`.

### `discover_manifests` (L274-291) — public
Scans repo root for known manifest filenames (`_MANIFEST_FILES`) plus `requirements*.txt` pattern. Returns list of `(relative_path, ecosystem)`.

### `parse_manifest` (L530-539) — public
Dispatches to correct parser by filename. Handles `_REQUIREMENTS_PATTERN` fallback.

### `scan_imports` (L544-610) — public
Builds a combined regex of all `import_names` from candidates, scans all non-ignored source files (excludes shadow dir, manifest files themselves). Updates `hit_files` and `import_hits` on each candidate in-place.

### Parser functions (internal)
- `_parse_requirements_txt` (L296-319): handles requirements.txt/setup.cfg/Pipfile
- `_parse_pyproject_toml` (L322-406): handles PEP 517 `project.dependencies`, `optional-dependencies`, Poetry `tool.poetry.dependencies`, `tool.poetry.group`, and `build-system.requires`; marks dev groups by name (`_dev_group_names`)
- `_parse_package_json` (L409-437): handles `dependencies`, `devDependencies`, `peerDependencies`
- `_parse_cargo_toml` (L440-476): handles `dependencies`, `dev-dependencies`; supports crate renames via `package` key
- `_parse_go_mod` (L479-516): handles single-line and block `require` directives

### `_resolve_import_names_heuristic` (L98-119) — internal
Fast local mapping: checks `_IMPORT_NAME_CACHE` first, then applies per-ecosystem rules (Python: hyphen→underscore, Node: identity, Rust: hyphen→underscore, Go: last path segment).

### LLM batch functions (internal, async)
- `_resolve_import_names_batch_async` (L138-190): uses `resolve_import_names` tool, validates all packages resolved
- `_classify_deps_batch_async` (L202-257): uses `classify_deps` tool with manifest context, validates all classified. Returns `(genuine_candidates, classification_map, in_tok, out_tok)`

## Key Data Structures

### `_IMPORT_NAME_CACHE` (L41-67)
26-entry dict mapping known package names (lowercase) to their import names (e.g., `"pillow" → ["PIL"]`).

### `_BUILD_TOOLS_CACHE` (L71-95)
Set of ~80 known build/dev tool package names for fast pre-filtering before LLM.

### `_MANIFEST_FILES` (L262-269)
Maps filename → ecosystem: `pyproject.toml`→python, `setup.cfg`→python, `Pipfile`→python, `package.json`→node, `Cargo.toml`→rust, `go.mod`→go.

### `_PARSERS` (L519-527)
Maps filename → parser function.

## Pipeline Architecture
```
discover_manifests → parse_manifest(s) → [LLM] resolve_import_names → scan_imports
  → filter zero-import → pre-filter BUILD_TOOLS → [LLM] classify_deps
  → finding_from_dep_candidate → build_junk_claims → decide_junk_claims
  → JunkFinding (confirmed only)
```

## Important Notes
- `setup.cfg` and `Pipfile` use `_parse_requirements_txt` as best-effort fallback (noted in `_PARSERS` comments at L522-523)
- Import scanning uses word-boundary regex `(?<!\w)...\n(?!\w)` — catches plain text mentions, not just formal imports
- Batch size limits: 80 for import name resolution (L678), 50 for classification (L729)
- All parsers are tolerant of missing `tomllib`/`tomli` (return empty list on ImportError)
- `detect_dead_deps_async` returns ALL decided findings; callers filter for `verdict == "confirmed"` (L791)
