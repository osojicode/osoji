# src\osoji\doc_analysis.py
@source-hash: aa6847f84c3876ce
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:18Z

## Purpose
Unified documentation analysis pipeline: discovers doc files, classifies them via Diataxis framework, validates accuracy against shadow docs, and triages findings through a unified LLM-backed verification stage.

## Architecture Overview
Two-tier source matching feeds a large-model analysis call. After all docs are analyzed in parallel, a unified Triage post-pass (`_triage_doc_findings`) replaces the old per-doc verify gate.

**Flow:** `find_doc_candidates` → `_find_referenced_sources` (Tier 1) + `_match_topics_async` (Tier 2) → `_analyze_document_async` → `_triage_doc_findings`

## Key Data Models

### `DocFinding` (L37-56)
Single finding from documentation analysis. Fields:
- `category`: stale_content | incorrect_content | obsolete_reference | misleading_claim
- `severity`: error | warning
- `shadow_ref`, `evidence`, `remediation`, `search_terms`
- Additive triage outputs: `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `finding_id` — all `None` until unified Triage stage decides

### `DocAnalysisResult` (L60-73)
Result for one doc file. Contains Diataxis `classification`, `confidence`, `classification_reason`, `matched_shadows`, `findings`, `topic_signature`.
- `is_debris` property (L72-73): returns `True` when `classification == "process_artifact"`

## Key Functions

### `find_doc_candidates(config)` (L79-120)
Discovers doc files in repo. Uses `list_repo_files` (git ls-files when available), skips `.osoji/` shadow dir, osojiignore patterns, and default ignore patterns. Returns sorted list of absolute Paths.

### `_find_referenced_sources(config, doc_content, *, doc_path, facts_db)` (L126-144)
Two-path resolution: fast FactsDB query (if `facts_db` has doc classification) returning imports as Paths, or regex fallback `_find_referenced_sources_regex`.

### `_find_referenced_sources_regex(config, doc_content)` (L147-184)
Regex-free substring matching: builds a dict of source file keys (full path, filename, Python module notation) from shadow doc filenames, checks each key against doc content. Keys < 4 chars are skipped.

### `_load_directory_summaries(config)` (L199-237)
Loads all directory shadow docs (`_directory.shadow.md`). Returns `dict[dir_key → (summary_text[:500], child_file_paths)]`. Used once per `analyze_docs_async` call.

### `_match_topics_async(provider, config, doc_content, dir_summaries)` (L240-308)
Tier 2: small model call using `match_doc_topics` tool. Doc truncated to 10K chars. Returns `(matched_source_paths, input_tokens, output_tokens, topic_signature)`. Maps returned directory paths back to child file paths.

### `_analyze_document_async(provider, config, doc_path, doc_content, shadow_contexts, rules_text)` (L371-461)
Large model call using `analyze_document` tool. Builds user prompt with file content, optional project rules, and shadow doc contexts. Filters findings by `confirmed: true` boolean. Raises `RuntimeError` if LLM doesn't call the tool. Returns `(DocAnalysisResult, input_tokens, output_tokens)`.

### `analyze_docs_async(provider, config, on_progress)` (L470-606)
Main orchestrator. Processes all candidates in parallel via `gather_with_buffer`. Per doc: reads file safely, truncates at 50K chars, runs Tier 1 + Tier 2 matching, caps shadow contexts at `_SHADOW_CHAR_CAP` (300K chars / ~75K tokens), runs large-model analysis. After all docs: runs `_triage_doc_findings` as best-effort post-pass. Degradation errors recorded to `config.audit_degradations` (dynamically attached attribute).

### `_triage_doc_findings(provider, config, results)` (L609-664)
Unified triage post-pass for all DocFindings. Converts each `DocFinding` to a `Finding` via `finding_from_doc`, builds claims via `build_junk_claims`, decides via `decide_junk_claims` with `TRIAGE_SYSTEM_PROMPT`. Verdict handling:
- `dismissed` → suppressed (filtered out)
- `uncertain` → kept, severity downgraded to "warning"
- `confirmed` → kept, severity may be re-graded from `fnd.severity`
- undecided → kept unverified
Rewrites `result.findings` in-place for non-debris results. Returns `(input_tokens, output_tokens)`.

## System Prompts

### `_MATCH_SYSTEM_PROMPT` (L189-196)
Instructs small model to identify relevant directories and populate `topic_signature` with purpose + 3-7 topic phrases.

### `_ANALYZE_SYSTEM_PROMPT` (L313-368)
Instructs large model on Diataxis classification (5 categories including `process_artifact` for debris), accuracy validation rules (commission=error, omission=warning), and `confirmed` boolean self-check semantics.

## Constants
- `_SHADOW_CHAR_CAP = 300_000` (L467): max shadow doc chars per doc analysis (~75K tokens)

## Dependencies
- `gather_with_buffer`: parallel execution with concurrency buffer
- `FactsDB`: fast doc-to-source reference lookups
- `finding_from_doc`: converts `DocFinding` → `Finding` for triage
- `build_junk_claims` / `decide_junk_claims`: triage claim pipeline
- `TRIAGE_SYSTEM_PROMPT`: shared triage prompt from `triage` module
- `get_match_doc_topics_tool_definitions` / `get_analyze_document_tool_definitions`: LLM tool schemas

## Critical Invariants
- `_triage_doc_findings` uses `id(r)` as keys in `kept` dict — relies on result objects not being garbage collected during the loop (safe since `results` list holds references)
- Triage post-pass is best-effort: failure keeps all findings unverified rather than dropping them
- Shadow char cap (L553-555) uses a `break` on first overflow — later source files are silently skipped even if individually smaller than the cap
- `config.audit_degradations` is a dynamically attached attribute, accessed via `getattr` with `None` default (L602)
