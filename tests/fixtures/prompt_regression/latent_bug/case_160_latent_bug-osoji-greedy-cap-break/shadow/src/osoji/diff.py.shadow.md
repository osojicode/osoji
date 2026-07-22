# src\osoji\diff.py
@source-hash: 66c1b469e3b5f445
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:52Z

## Purpose
Diff-aware impact analysis for the osoji documentation system. Compares `base_ref...HEAD` via `git diff`, classifies changed files as source or doc, detects stale/missing shadow docs for changed sources, and finds documentation files that reference changed sources.

## Key Dataclasses

### `DiffFileChange` (L18-24)
Represents a single changed file from `git diff`. Fields: `path` (relative to repo root), `change_type` (string: "modified"/"added"/"deleted"/"renamed"/"copied"/"type_changed"), `is_source` (bool), `is_doc` (bool).

### `StaleShadow` (L28-33)
A source file with a stale or missing shadow doc. Fields: `source_path`, `shadow_exists`, `status` ("stale"/"missing"/"deleted_source").

### `DocReference` (L37-44)
A documentation file that references a changed source. Fields: `doc_path`, `source_path`, `line_number`, `line_content`, `source_deleted` (bool, indicates high severity).

### `DiffImpactReport` (L48-60)
Complete result of a diff impact analysis. Holds `base_ref`, `changed_source`, `changed_docs`, `stale_shadows`, `doc_references`, and optional `config_snapshot`. The `has_issues` property (L59) returns True if there are any stale shadows or doc references.

## Key Functions

### `get_diff_files(repo_root, base_ref, config)` (L74-124)
Runs `git diff <base_ref>...HEAD --name-status` via subprocess. Parses tab-separated output, extracts the status letter (first char), uses the last tab-field as the destination path (handles renames). Applies both `config.ignore_patterns` and `.osojiignore` patterns via `_matches_ignore`. Maps status letters using `_STATUS_MAP` (L64-71). Returns list of `DiffFileChange`.

### `check_stale_shadows(config, changed_sources)` (L127-160)
For each changed source file: if deleted, appends a "deleted_source" `StaleShadow` (shadow may still exist); if missing on disk, skips; if shadow missing, appends "missing"; if shadow exists but `is_stale()` returns True, appends "stale".

### `find_doc_references(config, changed_sources)` (L163-177)
Dispatcher: loads `FactsDB` and checks for doc entries. If FactsDB has doc facts, uses fast `_find_doc_references_via_facts`; otherwise falls back to `_find_doc_references_via_grep`.

### `_find_doc_references_via_facts(config, facts_db, changed_sources)` (L180-228)
Uses `facts_db.docs_referencing(source_str)` for each changed source. For each referenced doc, scans file content for the source filename as a search term (line-level context). If exact line not found, emits a `DocReference` with `line_number=0` and a "(reference found via FactsDB)" placeholder.

### `_find_doc_references_via_grep(config, changed_sources)` (L231-276)
Fallback text-search. Uses `find_doc_candidates(config)` to enumerate all doc files, then searches each for either the full forward-slash path or the filename of each changed source. Only records the first pattern match per changed source per line (breaks after first pattern hit per source per line).

### `run_diff(config, base_ref)` (L279-306)
Primary orchestrator. Locates git root via `find_git_root`, calls `get_diff_files`, partitions changes into source/doc lists, calls `check_stale_shadows` and `find_doc_references`, returns a `DiffImpactReport`.

### `format_diff_report(report)` (L309-358)
Formats a `DiffImpactReport` as human-readable Markdown text. Sections: summary, stale shadow docs, doc references to changed source, and a final issue count.

### `format_diff_json(report)` (L361-401)
Serializes `DiffImpactReport` to JSON string. Includes `config_snapshot` only if not None.

## Module-Level Constant
`_STATUS_MAP` (L64-71): Maps single-letter git status codes to human-readable change type strings.

## Dependencies
- `config.Config`: root_path, shadow_path_for(), is_doc_candidate(), ignore_patterns, load_osojiignore(), config_snapshot, extensions
- `doc_analysis.find_doc_candidates`: enumerates candidate documentation files
- `facts.FactsDB`: provides `doc_files()` and `docs_referencing(source_str)` for fast lookups
- `hooks.find_git_root`: locates the git repository root
- `shadow.is_stale`: checks if a shadow doc is outdated relative to its source
- `walker._matches_ignore`: tests file paths against ignore patterns

## Architectural Notes
- Two-strategy doc reference lookup: FactsDB (fast, index-based) vs. grep (fallback, text-scan)
- Windows path compatibility: backslashes replaced with forward slashes before FactsDB/pattern matching (L189, L244)
- For renamed files, the destination path is used (`parts[-1]`, L105)
- `_find_doc_references_via_grep` uses a double-break pattern: once a source pattern matches a line, it stops checking other patterns for that source on that line (L272-274)