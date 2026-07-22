# tests\test_plumbing.py
@source-hash: edabd78e9cca552f
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:57Z

## Purpose
Test suite for the dead plumbing detection pipeline (`osoji.plumbing`), covering obligation extraction (Phase A via LLM), file-role querying helpers (`osoji.symbols`), and the full end-to-end pipeline through the unified Triage stage.

## File Structure Overview

### Helper Functions (L19–77)
- **`_triage_verdicts(options, verdicts_by_index)`** (L19–43): Constructs a mock `CompletionResult` with a `submit_triage_verdicts` ToolCall. Calls `options.tool_input_validators[0]("submit_triage_verdicts", {"verdicts": []})` to determine batch size `n`, then fills in verdicts from `verdicts_by_index` (defaulting to `("confirmed", 0.9, "unreachable")` for missing indices). Critical helper for testing the Triage stage.
- **`_write_symbols(temp_dir, source, symbols, file_role=None)`** (L48–61): Writes a `.osoji/symbols/<source>.symbols.json` sidecar with `source`, `source_hash`, `generated`, `symbols`, and optionally `file_role`.
- **`_write_source(temp_dir, path, content)`** (L64–68): Writes a source file at `temp_dir / path`, creating parent directories.
- **`_write_shadow(temp_dir, source, content)`** (L71–76): Writes a `.osoji/shadow/<source>.shadow.md` shadow doc file.

### Test Classes

#### `TestFileRoles` (L81–141)
Tests `load_file_roles` and `load_files_by_role` from `osoji.symbols`:
- **`test_load_file_roles_with_roles`** (L84–96): Verifies that files with `file_role` in sidecar are included in the returned dict.
- **`test_load_file_roles_skips_old_cache`** (L98–106): Files without `file_role` key (old cache format) are omitted.
- **`test_load_files_by_role`** (L108–117): Filters files by a specific role (e.g., `"schema"`).
- **`test_load_files_by_role_empty`** (L119–125): Returns empty list when no files match requested role.
- **`test_load_file_roles_no_symbols_dir`** (L127–131): Returns empty dict when `.osoji/symbols/` does not exist.
- **`test_doc_json_sidecar_is_excluded_from_schema_roles`** (L133–141): A JSON file that is a `config.is_doc_candidate` should NOT appear in `load_files_by_role("schema")` results, even if sidecar says `file_role="schema"`.

#### `TestExtractObligations` (L153–234)
Tests `extract_obligations_async` with a mocked LLM provider:
- **`test_extracts_obligations`** (L165–210): LLM returns two obligation-bearing fields; verifies `field_name`, `schema_name`, token counts returned.
- **`test_empty_obligations`** (L213–234): LLM returns empty obligations list; verifies result is `[]`.
- Fixtures: `mock_provider` (L157–158, `AsyncMock`), `config` (L161–162, uses `temp_dir` fixture from conftest).

#### `TestDetectDeadPlumbing` (L239–322)
Integration tests for `detect_dead_plumbing_async`:
- **`test_full_pipeline`** (L248–298): Sets up schema + source + shadow files. `mock_complete` dispatches on `options.tool_choice["name"]`—returns `extract_obligations` result or calls `_triage_verdicts`. Verifies `total==2`, only `taskTimeoutMs` is in `confirmed` verdicts.
- **`test_no_schema_files`** (L300–309): Only a `utility`-role sidecar present; expects `([], 0)` and zero LLM calls.
- **`test_doc_json_schema_sidecar_does_not_trigger_plumbing`** (L312–322): `docs/*.json` marked as schema should not enter plumbing analysis; expects `([], 0)` and zero LLM calls.

## Key Architectural Patterns
- **Triage stage dispatch**: The `mock_complete` function in `test_full_pipeline` dispatches on `options.tool_choice.get("name", "")` — this mirrors the real pipeline's tool-choice-based routing.
- **`_triage_verdicts`** introspects `options.tool_input_validators[0]` to determine batch size dynamically, coupling test helper tightly to the real `CompletionOptions` schema.
- **Doc-candidate exclusion**: Both `TestFileRoles` and `TestDetectDeadPlumbing` test that `config.is_doc_candidate` gates schema files out of plumbing analysis (L133–141, L312–322).
- Stale comment at L144–148 explains removal of `TestFieldReferences` class — clarifies that `_find_field_references` was superseded by `evidence_builders.CrossFileReferenceBuilder`.

## Dependencies
- `osoji.config.Config`: Used to configure root path and gitignore settings.
- `osoji.llm.types.CompletionResult`, `ToolCall`: Mock return values for LLM calls.
- `osoji.plumbing`: `ConfigObligation` (imported but not directly used in tests — may be used for type assertions), `detect_dead_plumbing_async`, `extract_obligations_async`.
- `osoji.symbols`: `load_file_roles`, `load_files_by_role`.
- `temp_dir` fixture is expected from a conftest (not in this file).

## Notable: `ConfigObligation` Import
`ConfigObligation` is imported at L12 but not visibly used in any test assertion in this file. It may be used for isinstance checks elsewhere, or the import is vestigial.
