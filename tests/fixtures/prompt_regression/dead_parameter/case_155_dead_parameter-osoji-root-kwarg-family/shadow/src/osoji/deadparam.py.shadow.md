# src\osoji\deadparam.py
@source-hash: 491508fe80182606
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:49Z

## Dead Parameter Detection Module

Implements two-phase dead parameter detection — finding function parameters that no caller ever passes — as part of the osoji junk analysis pipeline.

### Architecture

**Phase 1 — Candidate Scanning (L82–244):** Pure Python, no LLM. Loads all symbols, finds public functions with optional parameters, checks importers via FactsDB, then greps all plausible caller files for call sites. Produces `DeadParamCandidate` objects (one per function+param pair).

**Phase 2 — Unified Verification (L250–299):** Converts candidates to `Finding` objects via `finding_from_dead_param_candidate`, builds claims via `build_junk_claims`, then submits to `decide_junk_claims` (LLM-backed triage). Returns all decided `Finding`s; callers filter on `verdict == "confirmed"`.

### Key Types

- **`CallSite` (L35–40):** Dataclass capturing a grep match: `file_path`, `line_number`, `context` (±10 lines).
- **`DeadParamCandidate` (L44–52):** Dataclass representing a candidate dead parameter: source path, function name, param name, param line, default flag, and collected call sites.
- **`DeadParameterAnalyzer` (L302–350):** Concrete `JunkAnalyzer` subclass. Properties: `name="dead_params"`, `cli_flag="dead-params"`. `analyze_async` runs the full pipeline and filters to confirmed findings only, mapping them to `JunkFinding` objects.

### Key Functions

- **`scan_dead_param_candidates(config)` (L82–244):** Phase 1 entry point. Loads symbols, resolves importers, greps candidate files with regex patterns (word-boundary `\bfname\s*(`, plus class name for constructors). Filters out: internal symbols, functions with no importers, same-file matches inside the function body, shadow dir files, ignored files, doc candidates.
- **`detect_dead_params_async(provider, config, on_progress)` (L250–299):** Phase 2 entry point (async). Calls Phase 1, converts to Findings, runs Claim Builder + Triage pipeline, returns all decided findings.
- **`_extract_context(lines, line_number, radius=10)` (L58–67):** Returns ±radius lines of context with `>>>` marker at match line; 1-indexed input.
- **`_dedupe_call_sites(call_sites)` (L70–79):** Deduplicates by `(file_path, line_number, context)` key after sorting.

### Scanning Logic Details

- Uses `load_all_symbols(config)` for symbol data; symbols must have `kind`, `visibility`, `parameters` with `optional`/`has_default` fields.
- Determines class membership of methods via line-range containment (L126–135); adds class-name grep pattern for constructor matching (L176–177).
- Candidate files: defining file + all importers from FactsDB (L184–185).
- Skips: `SHADOW_DIR` paths (L194), `ignore_patterns` (L196), `.osojiignore` patterns (L198), doc candidates (L200).
- File content is cached in `file_lines_cache` dict (L115) across symbol iterations.

### JunkFinding Construction (L319–346)

Extracts `function_name` and `param_name` from `_scanner_meta(f)`. Sets `kind="parameter"`, `category="dead_parameter"`, `confidence_source="llm_inferred"`. Metadata includes `gated_lines=[]` (previously populated by a per-detector verify tool, now empty per L341–343 comment). `name` falls back to `"{function_name}.{param_name}"` if `f.symbol` is falsy.

### Dependencies

- `.config.Config`, `.config.SHADOW_DIR` — configuration and shadow directory sentinel
- `.evidence_builders.BuildContext`, `._scanner_meta` — claim building context and metadata extraction
- `.facts.FactsDB` — importer graph queries
- `.findings.Finding`, `.findings_adapter.finding_from_dead_param_candidate` — Finding conversion
- `.junk.JunkAnalyzer`, `.junk.JunkFinding`, `.junk.JunkAnalysisResult` — base analyzer protocol
- `.junk_triage.build_junk_claims`, `.decide_junk_claims` — LLM-backed triage pipeline
- `.llm.base.LLMProvider` — LLM abstraction
- `.symbols.load_all_symbols` — symbol loading
- `.walker.list_repo_files`, `._matches_ignore` — file enumeration and ignore filtering