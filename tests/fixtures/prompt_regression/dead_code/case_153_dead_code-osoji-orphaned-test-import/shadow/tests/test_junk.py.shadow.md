# tests\test_junk.py
@source-hash: 650905a551e1f964
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:52Z

## Purpose
Test suite for the unified junk code analysis framework (`osoji.junk`), covering `JunkFinding`, `JunkAnalysisResult`, `load_shadow_content`, analyzer registry properties, `DeadCodeAnalyzer`, `DeadPlumbingAnalyzer`, and `Config` path helpers.

## File Structure

### Helpers (L23–51)
- **`_write_shadow(temp_dir, source, content)`** (L23–28): Creates a `.osoji/shadow/<source>.shadow.md` file with given content for test fixtures.
- **`_write_symbols(temp_dir, source, symbols, file_role=None)`** (L31–44): Creates a `.osoji/symbols/<source>.symbols.json` sidecar with schema `{source, source_hash, generated, symbols, file_role?}`.
- **`_write_source(temp_dir, path, content)`** (L47–51): Writes a source file at `temp_dir/path`.

### TestJunkFinding (L56–95)
Tests `JunkFinding` dataclass/model construction:
- **`test_construction`** (L57–76): Validates all required fields plus `metadata` defaults to `{}`.
- **`test_metadata_default`** (L78–85): Confirms `metadata={}` default when omitted.
- **`test_metadata_custom`** (L87–95): Confirms custom `metadata` dict (e.g., `schema_name`) is preserved.

### TestJunkAnalysisResult (L100–109)
- **`test_construction`** (L101–109): Validates `findings`, `total_candidates`, `analyzer_name` fields on `JunkAnalysisResult`.

### TestLoadShadowContent (L114–128)
- **`test_loads_existing_shadow`** (L115–121): `load_shadow_content(config, path)` returns file content when shadow exists.
- **`test_returns_empty_for_missing`** (L124–128): Returns `""` when shadow file is absent.

### TestAnalyzerRegistry (L133–148)
- **`test_dead_code_analyzer_properties`** (L134–138): `DeadCodeAnalyzer.name == "dead_code"`, `cli_flag == "dead-code"`.
- **`test_dead_plumbing_analyzer_properties`** (L140–144): `DeadPlumbingAnalyzer.name == "dead_plumbing"`, `cli_flag == "dead-plumbing"`.
- **`test_analyzers_are_junk_analyzer_subclasses`** (L146–148): Both are subclasses of `JunkAnalyzer`.

### TestDeadCodeAnalyzer (L153–197)
- **`test_analyze_async_returns_junk_result`** (L155–197): Integration test for `DeadCodeAnalyzer.analyze_async(provider, config)`.
  - Writes a symbols sidecar with one symbol (`dead_func`), a stub source, and a second source without references.
  - Mocks `provider.complete` via `AsyncMock` returning a `CompletionResult` with a `submit_triage_verdicts` tool call.
  - Asserts `result.analyzer_name == "dead_code"`, one finding with `category == "dead_symbol"`, correct `source_path`, `name`, `kind`, `confidence`, `reason`, `remediation`.

### TestDeadPlumbingAnalyzer (L202–273)
- **`test_analyze_async_returns_junk_result`** (L204–273): Integration test for `DeadPlumbingAnalyzer.analyze_async(provider, config)`.
  - Writes schema file (`src/trial.ts`) with `file_role="schema"` and shadow; consumer file (`src/runner.ts`) with shadow.
  - `mock_complete` (L218–255) distinguishes two LLM calls:
    - First call (tool_choice contains `"extract_obligations"`): returns obligation for `taskTimeoutMs`.
    - Second call (triage): uses `options.tool_input_validators[0]` to determine batch size, returns confirmed verdicts for each obligation.
  - Asserts `result.analyzer_name == "dead_plumbing"`, `total_candidates == 1`, one finding with `category == "unactuated_config"`, `kind == "config_field"`, `metadata["schema_name"] == "Schema"`.

### TestConfigJunkPath (L278–283)
- **`test_analysis_junk_path_for`** (L279–283): Validates `config.analysis_junk_path_for("dead_code", Path("src/utils.py"))` produces `<analysis_root>/junk/dead_code/src/utils.py.dead_code.json`.

## Key Dependencies
- `osoji.junk`: `JunkAnalyzer`, `JunkAnalysisResult`, `JunkFinding`, `load_shadow_content`
- `osoji.deadcode`: `DeadCodeAnalyzer`
- `osoji.plumbing`: `DeadPlumbingAnalyzer`
- `osoji.config`: `Config`
- `osoji.llm.types`: `CompletionResult`, `ToolCall`
- `pytest` with `asyncio` mark for async tests
- `unittest.mock.AsyncMock` for LLM provider mocking

## Notable Patterns
- Tests rely on a `temp_dir` fixture (not defined in this file — expected from `conftest.py`).
- `mock_complete` for `DeadPlumbingAnalyzer` uses `options.tool_input_validators[0]` to dynamically determine batch size, mirroring production triage logic.
- Sidecar JSON schema includes `source_hash` and `generated` fields, reflecting the actual symbols file format.
- The `file_role` field in sidecar JSON is optional and only written when provided (L42–43), matching the schema file detection logic in `DeadPlumbingAnalyzer`.