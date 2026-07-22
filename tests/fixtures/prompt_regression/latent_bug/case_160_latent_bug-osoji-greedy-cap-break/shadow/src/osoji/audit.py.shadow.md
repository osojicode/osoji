# src\osoji\audit.py
@source-hash: 5e57593a3a0ff854
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:21Z

## Purpose
Central orchestration module for the Osoji documentation audit system. Coordinates all audit phases (shadow docs, doc analysis, debris triage, obligations, junk analyzers, scorecard, doc prompts), manages the incremental verdict cache, and provides output formatting (markdown, JSON, HTML).

## Key Data Structures

### `AuditIssue` (L102-125)
Dataclass for a single audit finding. Fields: `path`, `severity` ("error"/"warning"/"info"), `category`, `message`, `remediation`, optional line range, `origin` dict (source+plugin), `exclude_key` (phase identifier for `--exclude`), `contract_class` (obligations taxonomy), and Triage overlay fields (`finding_id`, `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`). Triage fields are additive — `None` when Triage didn't run.

### `AuditResult` (L128-147)
Dataclass containing `issues: list[AuditIssue]`, `scorecard: Scorecard | None`, `config_snapshot: dict | None`, `doc_prompts: Any | None`. Properties: `has_errors`, `has_warnings`, `passed` (no errors).

## Phase Registry

### `JUNK_ANALYZERS` (L72-79)
Registry of all junk analyzer classes: `DeadCodeAnalyzer`, `DeadParameterAnalyzer`, `DeadPlumbingAnalyzer`, `DeadDepsAnalyzer`, `DeadCICDAnalyzer`, `OrphanedFilesAnalyzer`. New analyzers must be added here.

### `EXCLUDABLE_PHASES` (L82-84)
Valid `--exclude` identifiers: `["shadow", "doc-analysis", "debris", "obligations", "doc-prompts"]` + each analyzer's `cli_flag`.

### `_CLI_FLAG_TO_PRODUCER` (L92-99)
Maps CLI flags to detector prefix strings used in `Finding.detector` for producer-scoped manifest merge (V1-9).

## Core Entry Points

### `run_audit` (L305-339)
Sync wrapper — calls `asyncio.run(run_audit_async(...))`. Accepts all phase flags plus `incremental`, `since`.

### `run_audit_async` (L342-791)
Primary async orchestrator. Phase sequence:
1. **Phase 1** (L432-460): Shadow doc check + optional auto-fix (`generate_shadow_docs_async`). Sequential; all later phases depend on shadow docs.
2. **Phases 2-4** (L462-499): Run concurrently via `asyncio.gather`:
   - Phase 2 (`_run_phase2_async`): doc analysis via `analyze_docs_async`
   - Phase 3 (`_run_phase3_async`): debris triage via `build_debris_claims` + `decide_junk_claims`
   - Phase 3.5 (`_run_phase3_5_async`): obligations — heuristic propose → Claim Builder → Triage
   - Phase 4 (`_run_phase4_async`): junk analyzers
3. **Phase 5** (L636-664): Scorecard build via `build_scorecard`. Serialized to `scorecard_path`.
4. **Phase 5.5** (L666-696): Optional `build_doc_prompts_async`. Re-serializes scorecard.
5. **Manifest write** (L737-776): V1-9 producer-scoped manifest merge via `merge_verdicts` + `write_manifest`. Best-effort; failure recorded as degradation, never fails the audit.
6. **Decided-findings ledger** (L784-789): Written to `analysis_root/decided-findings.json` for `osoji corpus emit`.

Key side effects on `config` object: `config.verdict_session = session` (L413), `config.audit_degradations = []` (L416), `config.decided_ledger = []` (L420).

## Phase Functions

### `_run_phase2_async` (L828-841)
Creates an LLM runtime, calls `analyze_docs_async`, returns `(results, phase_tokens)`.

### `_run_phase3_async` (L844-908)
Debris triage. Loads eligible raw debris → `build_debris_claims` → `decide_junk_claims`. `dismissed` verdict suppresses finding. Returns `(suppressed_indices, phase_tokens, decided_by_index)`. Best-effort; on failure keeps all findings and records degradation.

### `_run_phase3_5_async` (L936-1005)
Obligations phase. `run_all_contract_checks` (heuristic propose) → `build_claims` → `decide_junk_claims` (Triage). `dismissed` suppresses; `_overlay_verdict` adds triage outputs to kept `ContractFinding`. Returns `(kept, tokens, triaged, other)`.

### `_run_phase4_async` (L1008-1063)
Runs enabled junk analyzers concurrently. `DeadCICDAnalyzer` requires `discover_cicd_files`; others require symbols dir. Each analyzer uses its own runtime; results collected by name.

### `_load_raw_debris` (L794-825)
Sync I/O: reads `*.findings.json` from `.osoji/findings/`, validates hash currency via `is_findings_current`, applies ignore patterns, flattens to list of dicts.

## Serialization / Deserialization

### `serialize_audit_result` (L1066-1071)
Persists `AuditResult` to `.osoji/analysis/audit-result.json`.

### `load_audit_result` (L1074-1167)
Reconstructs `AuditResult` (with full `Scorecard` and optional `DocPromptsResult`) from JSON file.

### `format_audit_json` (L1428-1462)
Produces JSON string for CI/machine consumption.

### `format_audit_report` (L1331-1425)
Produces agent-ready Markdown report with sections: Scorecard, Doc Opportunities, Errors, Warnings, Info, Implicit String Contracts.

### `format_audit_html` (L2422-2531)
Produces self-contained HTML dashboard with light/dark theme toggle, metric cards, coverage matrix, junk code analysis, file health, enforcement, and doc prompts sections. Requires `_AUDIT_CSS` (L1479-1743), `_HANKO_SVG` (L1469-1477), and several `_html_*` section builders.

## Re-exported Symbols (claim_builder)
L35-41: `_extract_all_symbols_from_debris`, `_infer_variable_type`, `_is_eligible`, `_lookup_type_definitions`, `build_debris_claims` — imported with `noqa: F401` as backwards-compatible re-exports.

## Incremental Audit (V1-9)
- `use_cache = (incremental or since is not None) and not config.force` (L387)
- `cache_from_verdicts` populates `verdict_cache`; `VerdictSession` tracks hits
- `merge_verdicts` does producer-scoped merge: producers that ran this session replace their entries; producers not run are preserved from previous manifest
- `manifest_current` check: manifest from different osoji version contributes nothing

## Progress Callbacks
- `_make_progress_default` (L197-220): inline carriage-return progress bar
- `_make_progress_verbose` (L223-243): one line per file

## Degradation Tracking
`_record_degradation` (L177-186) and `_degraded_phases` (L189-194) use `getattr(config, "audit_degradations", None)` for safe access when called outside `run_audit_async`. Degraded phases surface in `scorecard.degraded_phases` and the audit report.

## Notable Patterns
- Analysis directory wiped fresh each run (L427-429): `shutil.rmtree(analysis_root)`
- All phase exclusions via `_exclude = exclude or set()` (L381), checked before creating coroutines
- `_tabulate` fallback implementation (L56-68) when `tabulate` package not installed
- `_overlay_verdict` (L911-933) uses `dataclasses.replace` for immutable `ContractFinding` update
- HTML uses inline `_h()` (L1746-1748) = `html.escape` throughout to prevent XSS in report