# src\osoji\junk.py
@source-hash: c4381da6096891fe
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:06Z

## Purpose
Defines the unified junk code analysis framework: shared dataclasses (`JunkFinding`, `JunkAnalysisResult`), the abstract base class `JunkAnalyzer`, and shared utility functions used by all junk detection analyzers (dead code, dead plumbing, etc.). Implements the two-phase pattern: cheap Python candidate filter → LLM verification.

## Key Symbols

### `JunkFinding` (L18-47) — dataclass
Represents a single confirmed junk item. Key fields:
- `source_path`, `name`, `kind`, `category` — identification
- `line_start` / `line_end` — location (validated in `__post_init__`: `line_end >= line_start`)
- `confidence` (0.0–1.0), `reason`, `remediation`, `original_purpose` — analysis output
- `confidence_source` — one of `"ast_proven"`, `"llm_inferred"`, `"heuristic"` (default `"llm_inferred"`)
- `metadata: dict[str, Any]` — extensible per-analyzer data
- `finding_id`, `verdict` — triage outputs, optional

**Invariant:** `line_end`, if set, must be `>= line_start`; enforced at construction via `__post_init__` (L42-47).

### `JunkAnalysisResult` (L50-56) — dataclass
Result container for a single analyzer run:
- `findings: list[JunkFinding]` — confirmed junk only
- `total_candidates: int` — total items examined
- `analyzer_name: str`

### `JunkAnalyzer` (L59-122) — ABC
Abstract base class for all junk analyzers. Subclasses must implement:
- `name` property (L67-70) — short identifier (e.g. `"dead_code"`)
- `description` property (L73-75) — human-readable description
- `cli_flag` property (L79-81) — CLI flag name without `--` prefix
- `analyze_async(provider, config, on_progress)` (L84-101) — primary async analysis method

**`analyze(config)` (L103-122):** Sync wrapper. Checks for `<shadow_dir>/symbols` directory; if missing, prints skip message and returns empty result. Otherwise creates `LLMProvider` via `create_runtime`, runs `analyze_async`, and ensures provider cleanup via `finally` block. Uses `asyncio.run()`.

### `validate_line_ranges(_tool_name, tool_input)` (L125-144) — function
Tool input validator for `CompletionOptions.tool_input_validators`. Checks `findings`, `items`, and `obligations` arrays in a tool input dict, ensuring `line_end >= line_start` for each item. Returns a list of error strings (empty if valid).

### `load_shadow_content(config, relative_path)` (L147-158) — function
Loads shadow doc markdown for a given relative source path. Resolves path as `<shadow_root>/<relative_path>.shadow.md`. Returns empty string if file doesn't exist or raises `OSError`.

## Architecture & Patterns
- **Two-phase analyzer pattern**: analyzers gather candidates cheaply (AST/static), then verify via LLM.
- **Sync/async bridge**: `JunkAnalyzer.analyze()` is a sync convenience wrapper around the async `analyze_async()`, using `asyncio.run()`.
- **Provider lifecycle**: `create_runtime` constructs provider; `analyze()` always calls `provider.close()` in `finally`.
- **Shared utilities**: `validate_line_ranges` and `load_shadow_content` are designed to be imported and reused by all concrete analyzer implementations.
- **Extensibility**: `JunkFinding.metadata` dict allows analyzer-specific extra data without changing the shared schema.

## Dependencies
- `.config`: `Config` (project config object), `SHADOW_DIR` (shadow directory constant)
- `.llm.base`: `LLMProvider` (abstract LLM provider interface)
- `.llm.runtime`: `create_runtime` (factory returning `(logging_provider, _)` tuple)
