# src\osoji\scorecard.py
@source-hash: 5d66197fce163e30
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:55Z

## Purpose
Pure-Python aggregation of audit phase results into headline metrics. No LLM calls. Takes `DocAnalysisResult` list and optional `JunkAnalysisResult` dict, returns a populated `Scorecard` dataclass covering documentation coverage, dead docs, accuracy, junk code, and enforcement metrics.

## Key Data Structures

### `CoverageEntry` (L14-17)
Dataclass linking a source file path to its `topic_signature` (from `.osoji` signatures JSON) and a list of covering doc dicts `{"path": str, "classification": str}`.

### `JunkCodeEntry` (L21-26)
Dataclass per source file: `source_path`, `total_lines`, `junk_lines`, `junk_fraction`, `items` (list of raw junk finding dicts).

### `Scorecard` (L30-91)
Central aggregation dataclass with fields across five concern areas:
- **Coverage** (L32-38): `coverage_entries`, `coverage_pct`, `covered_count`, `total_source_count`, `coverage_by_type`, `type_covered_counts`, `type_total_counts`
- **Dead docs** (L41): `dead_docs` — paths of `is_debris` analysis results
- **Accuracy** (L44-47): `total_accuracy_errors`, `live_doc_count`, `accuracy_errors_per_doc`, `accuracy_by_category`
- **Junk code** (L50-58): line counts, fractions, item/file counts, per-category breakdowns, `junk_entries`, `junk_sources`
- **Enforcement** (L61-64): optional fields populated only when `dead_plumbing` junk analyzer ran
- **Optional fields** (L67-91): `obligation_violations`, `obligation_implicit_contracts`, contract claim triage fields, `verdict_cache_hit_rate`, concept-centric coverage, `degraded_phases` — **all default `None`**, must be set by callers after construction

## Key Functions

### `merge_ranges(ranges)` (L94-106)
Merges overlapping integer `(start, end)` tuples into a sorted, non-overlapping list. Used to deduplicate junk line ranges across findings for accurate line counts. Adjacent ranges (start ≤ prev_end + 1) are merged.

### `count_lines(path)` (L109-114)
Reads file text (errors ignored) and returns line count. Returns 0 on `OSError`.

### `_load_signature(config, source_path)` (L117-125)
Internal helper. Calls `config.signatures_path_for()` to locate the JSON signature file for a source path, parses it, returns dict or None on missing/invalid.

### `build_scorecard(config, analysis_results, junk_results=None)` (L128-354)
**Primary entry point.** Five-phase computation:

1. **Coverage** (L136-190): Scans `config.shadow_root` for `*.shadow.md` files (skips `DIRECTORY_SHADOW_FILENAME` and doc candidates). Inverts `matched_shadows` from `DocAnalysisResult` to map source→covering docs. Computes `coverage_pct` and per-Diataxis-type breakdown.

2. **Dead docs** (L192-193): Collects paths where `item.is_debris` is True.

3. **Accuracy** (L195-206): Counts findings with `severity == "error"` across live (non-debris) results.

4. **Junk code** (L208-305): Two sources merged into `junk_items_by_file`:
   - `findings_dir` (`config.root_path / SHADOW_DIR / "findings"`) — legacy `*.findings.json` files, validated via `is_findings_current()` (L221-224)
   - `junk_results` dict keyed by analyzer name — richer finding objects with `confidence_source`, `name`, `kind`, `reason`, `remediation`, `confidence` fields
   
   Per-file: calls `merge_ranges()` on `(line_start, line_end)` tuples to count deduplicated junk lines. Denominator for `junk_fraction` is total lines across ALL source files (L265-269), not just files with junk.

5. **Enforcement** (L307-327): Extracts `dead_plumbing` from `junk_results`; if present, computes `enforcement_total_obligations`, `enforcement_unactuated`, `enforcement_pct_unactuated`, and groups by `"{source_path}:{schema_name}"` key.

## Important Dependencies
- `Config.shadow_root`, `Config.root_path`, `Config.signatures_path_for()`, `Config.is_doc_candidate()` — drives file discovery
- `DIRECTORY_SHADOW_FILENAME`, `SHADOW_DIR` — sentinel values for path filtering
- `DocAnalysisResult.is_debris`, `.matched_shadows`, `.classification`, `.findings`, `.path` — consumed from doc analysis phase
- `JunkAnalysisResult.findings`, `.total_candidates` — consumed from junk analysis phase
- `is_findings_current(source_hash, impl_hash, path)` — stale-cache guard for legacy findings files

## Architectural Notes
- `Scorecard` optional fields (L67-91) are intentionally `None` by default; callers (e.g., `audit.py`) are responsible for populating them post-construction.
- Junk line counting uses range merging to avoid double-counting overlapping findings.
- Legacy `code_debris` findings path (L213-236) coexists with the newer `junk_results` dict path; both populate the same `junk_items_by_file` dict.
- Source file enumeration is driven by shadow inventory (`.shadow.md` files), not by walking the source tree directly.