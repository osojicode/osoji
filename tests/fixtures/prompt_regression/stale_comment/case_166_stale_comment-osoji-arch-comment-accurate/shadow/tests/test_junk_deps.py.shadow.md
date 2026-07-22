# tests\test_junk_deps.py
@source-hash: afc93c7e08cb6721
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:26Z

## Purpose
Test suite for `osoji.junk_deps` — the dead dependency detection module. Validates manifest discovery, dependency parsing (requirements.txt, pyproject.toml, package.json), import name resolution, import scanning, LLM-based classification, and the full end-to-end `detect_dead_deps_async` / `DeadDepsAnalyzer` pipeline.

## Key Fixtures & Helpers

### `_triage_verdicts` (L29–49)
Builds a mock `CompletionResult` simulating a `submit_triage_verdicts` tool call response. Introspects the `options.tool_input_validators[0]` to determine the batch size `n`, then fills `verdicts_by_index` overrides, defaulting unspecified indices to `("confirmed", 0.85, "no import or config use")`. Used in integration tests to mock the unified triage LLM step.

### `_write_source` (L54–58)
Helper writing arbitrary content to `temp_dir / path`, creating parent directories as needed.

## Test Classes

### `TestDiscoverManifests` (L63–97)
Tests `discover_manifests(config)` returns `(path, ecosystem)` tuples for:
- `pyproject.toml` → python
- `requirements.txt` → python
- `requirements-dev.txt` → python (glob pattern)
- `package.json` → node
- Empty directory → `[]`

### `TestParseRequirements` (L102–133)
Tests `_parse_requirements_txt(content, filename)` producing `DependencyCandidate` objects:
- Simple package names, version specifiers with extras
- Skips comments, blank lines, pip directives (`-r`, `-c`, `-e`, `-f`)
- Correct 1-based `line_number` assignment

### `TestParsePyproject` (L138–190)
Tests `_parse_pyproject_toml(content, filename)`:
- `[project].dependencies` → regular deps
- `[project.optional-dependencies]` → `is_dev=True`
- `[tool.poetry.dependencies]` → excludes `python` keyword
- `[tool.poetry.group.dev.dependencies]` → `is_dev=True`
- `[build-system].requires` → build deps included

### `TestParsePackageJson` (L195–230)
Tests `_parse_package_json(content, filename)`:
- `dependencies` → `is_dev=False`
- `devDependencies` → `is_dev=True`
- `peerDependencies` → included
- Scoped packages (`@types/node`, `@scope/pkg`) preserved as-is

### `TestResolveImportNames` (L235–267)
Tests `_resolve_import_names_heuristic(package_name, ecosystem)`:
- Known mismatches: Pillow→PIL, scikit-learn→sklearn, PyYAML→yaml
- Heuristic fallback: hyphen→underscore (`my-package` → `my_package`)
- Node: exact name pass-through, scoped packages preserved
- Rust: hyphen→underscore
- Go: last path segment extracted

### `TestScanImports` (L271–328)
Tests `scan_imports(config, candidates)` mutating `DependencyCandidate.import_hits` and `hit_files`:
- Finds matching imports in source files
- Word-boundary matching: `not_requests` does NOT match `requests` (underscore+letter = no `\b`)
- Scoped npm packages (`@modelcontextprotocol/sdk`) detected in TypeScript imports
- Multiple import names (Pillow with import_names=["PIL"])

### `TestFilterZeroImport` (L332–374)
Tests `_filter_zero_import(candidates)`:
- Candidates with `import_hits=0` pass through (both)
- Candidates with `import_hits>0` are excluded

### `TestBuildToolsCache` (L379–396)
Validates exported module-level caches:
- `_BUILD_TOOLS_CACHE`: contains `black`, `ruff`, `pytest`, `mypy`, `typescript`, `eslint`, `webpack`
- `_IMPORT_NAME_CACHE`: contains `pillow`→`["PIL"]`, `scikit-learn`

### `TestHaikuImportResolution` (L401–435)
Tests `_resolve_import_names_batch_async(provider, [(pkg, ecosystem), ...])` with mocked `provider.complete`:
- Returns `(dict[pkg→[import_names]], in_tokens, out_tokens)`
- Empty input short-circuits without calling LLM

### `TestHaikuDepClassification` (L440–485)
Tests `_classify_deps_batch_async(provider, candidates, source_text)` with mocked LLM:
- Returns `(genuine_candidates, class_map, in_tok, out_tok)`
- Filters out `build_tool` classification, keeps `genuine_candidate`
- Empty input short-circuits

### `TestDetectDeadDepsAsync` (L497–566)
Integration tests for `detect_dead_deps_async(provider, config)`:
- Full pipeline: `requests` has imports → filtered out; `old-unused` → zero imports → triage → confirmed dead. Returns `(decided_findings, total_count)` where `total==1`, `confirmed[0].symbol=="old-unused"`.
- Empty manifests → `([], 0)`
- All packages imported → `([], 0)` (no zero-import candidates)

### `TestDeadDepsAnalyzer` (L571–637)
Tests `DeadDepsAnalyzer` high-level API:
- `analyze_async(provider, config)` returns `JunkAnalysisResult` with `analyzer_name=="dead_deps"`, findings with correct fields: `source_path`, `name`, `kind=="dependency"`, `category=="dead_dependency"`, `confidence`, `metadata["usage_type"]=="unused"`
- Properties: `name=="dead_deps"`, `cli_flag=="dead-deps"`, description contains "dependencies" or "deps"
- Is subclass of `JunkAnalyzer`

## Architecture Notes
- Mock pattern for multi-step LLM pipelines: `mock_provider.complete.side_effect = mock_complete` dispatches on `options.tool_choice["name"]` to simulate different tool responses per pipeline stage.
- The `_triage_verdicts` helper uses `options.tool_input_validators[0]` to introspect batch size, coupling test helper to internal options structure.
- Note at L488–492 documents migration from deleted `_verify_batch_async` to unified Triage pipeline, referencing `test_junk_project_graph_cutover.py` for gate tests.
- All async tests use `@pytest.mark.asyncio`.
- `temp_dir` fixture is provided externally (likely `conftest.py` as a `tmp_path`-based fixture).