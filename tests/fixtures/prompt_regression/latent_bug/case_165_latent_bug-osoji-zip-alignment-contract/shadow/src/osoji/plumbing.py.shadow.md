# src\osoji\plumbing.py
@source-hash: aa704b63cfee161a
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:55Z

## Purpose
Implements the "dead plumbing" detector: an LLM-assisted pipeline that finds schema/config fields that declare behavioral obligations (timeouts, rate limits, size limits, etc.) but are never actuated in application code. Integrates into the unified `JunkAnalyzer` framework.

## Key Components

### `ConfigObligation` (L29–39)
Dataclass representing a schema field with a declared behavioral obligation. Fields:
- `source_path`: file path of the schema
- `field_name`: e.g., `"taskTimeoutMs"`
- `schema_name`: e.g., `"TrialSettingsSchema"`
- `line_start` / `line_end`: source location
- `obligation`: what the field promises
- `expected_actuation`: what enforcement code would look like
- `evidence`: direct quote from schema text (optional, defaults to `""`)

### `_EXTRACT_OBLIGATIONS_SYSTEM_PROMPT` (L44–72)
System prompt instructing the LLM to identify obligation-bearing fields (timeouts, limits, TTLs, etc.) — NOT identity, shape, or metadata fields, and NOT LLM tool schema constraints. Requires textual grounding; never infer from field names alone.

### `extract_obligations_async` (L75–122)
**Phase A** of the pipeline. Calls the `small` model with forced `extract_obligations` tool use. Parses each tool call result into `ConfigObligation` instances. Raises `RuntimeError` if the LLM doesn't call the tool. Returns `(obligations, input_tokens, output_tokens)`.

### `detect_dead_plumbing_async` (L127–194)
**Full pipeline orchestrator**:
1. Loads schema files via `load_files_by_role(config, "schema")` (L145)
2. Parallel extraction: `extract_one` inner async function (L153–172) reads file content, loads shadow content, calls `extract_obligations_async`; parallelized via `gather_with_buffer` (L174)
3. Converts obligations → `Finding`s via `finding_from_config_obligation` (L188)
4. Builds claims via `build_junk_claims` (L190) and triages via `decide_junk_claims` (L191–193)
5. Returns `(decided_findings, total_obligations_count)`

### `DeadPlumbingAnalyzer` (L197–239)
Concrete `JunkAnalyzer` subclass:
- `name = "dead_plumbing"` (L202)
- `cli_flag = "dead-plumbing"` (L210)
- `analyze_async` (L212–239): Calls `detect_dead_plumbing_async`, filters to `confirmed` verdicts, maps each `Finding` to a `JunkFinding` with `kind="config_field"`, `category="unactuated_config"`, `confidence_source="llm_inferred"`. Falls back to `"Add enforcement for `{field_name}`"` for remediation if no `suggested_fix`.

## Architecture Notes
- Two-phase pipeline: Phase A (LLM obligation extraction per schema file) → unified triage (claim building + LLM verdict)
- `gather_with_buffer` provides concurrent LLM calls with backpressure
- Schema file discovery is shadow-doc-driven (`load_files_by_role`)
- Source content is truncated to 30,000 chars (L88) before sending to LLM
- `_scanner_meta(f)` (L218) retrieves field-level metadata embedded in the `Finding` by `finding_from_config_obligation`

## Dependencies
- `gather_with_buffer`: async parallelism with buffering
- `load_files_by_role`: shadow-doc-based file role lookup
- `finding_from_config_obligation`: converts `ConfigObligation` → `Finding`
- `build_junk_claims` / `decide_junk_claims`: unified triage pipeline
- `get_extract_obligations_tool_definitions`: LLM tool schema for Phase A
- `input_budget_for_config`: computes max input tokens from config
