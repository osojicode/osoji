# tests\test_deadparam.py
@source-hash: 0bad6762b11164a8
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:51Z

## Purpose
Test suite for the `osoji.deadparam` module covering dead parameter detection (Phase 1: candidate scanning, Phase 2: LLM-backed triage pipeline). All LLM provider calls are mocked — no real network calls occur.

## File Structure

### Helper Functions (L22–60)
- `_write_shadow(temp_dir, source)` (L22): Writes a `.osoji/shadow/<source>.shadow.md` stub with a fixed `@source-hash: abc` header.
- `_write_source(temp_dir, path, content)` (L29): Creates a source file at `temp_dir/path` with placeholder or provided content.
- `_write_symbols(temp_dir, source, symbols, file_role)` (L35): Writes a `.osoji/symbols/<source>.symbols.json` fixture with `source`, `source_hash`, `file_role`, and `symbols` fields.
- `_write_facts(temp_dir, source, imports, exports, calls)` (L48): Writes a `.osoji/facts/<source>.facts.json` fixture with `imports`, `exports`, `calls`, and `string_literals` fields.

All helpers use `temp_dir` (a `pytest` fixture providing a temporary `pathlib.Path` directory).

### TestScanCandidates (L65–313)
Tests for `scan_dead_param_candidates(config)`. All tests patch `osoji.deadparam.list_repo_files` to control which files are visible.

- `test_function_with_optional_params_and_callers` (L66): Verifies that a public function with optional params AND external callers produces `DeadParamCandidate` entries for optional params only.
- `test_function_with_no_optional_params_skipped` (L121): Verifies functions with no optional params produce zero candidates.
- `test_function_with_no_callers_skipped` (L148): Verifies functions with optional params but zero importers are skipped (responsibility delegated to dead-code analyzer).
- `test_internal_functions_skipped` (L172): Verifies `visibility="internal"` functions are excluded.
- `test_symbols_without_parameters_skipped` (L195): Backward-compatibility: symbols without a `parameters` field are gracefully skipped.
- `test_dotted_method_name_matches_instance_calls` (L219): Verifies `Class.method` symbol names match instance call patterns (e.g., `obj.method(...)`).
- `test_common_name_scan_only_checks_importers` (L269): Verifies that call-site collection only searches importer files, not unrelated files that happen to define a same-named function.

### TestDetectDeadParams (L318–422)
Tests for `detect_dead_params_async(provider, config)` using `AsyncMock` LLM providers returning `CompletionResult` with `ToolCall` verdicts.

- `_write_env(temp_dir)` (L321): Shared fixture builder creating `src/scorecard.py` + `src/audit.py` with `build_scorecard` having optional `dead_code_results` param.
- `test_confirmed_param_decided_through_triage` (L357): Mock provider returns `verdict="confirmed"` → resulting `JunkFinding` has `detector="deadparam:dead_parameter"`, `gap_type="reachability"`, `symbol="build_scorecard.dead_code_results"`, `triage_reasoning`, and `evidence` containing `"scanner_metadata"`.
- `test_dismissed_param_kept_with_verdict` (L390): Mock provider returns `verdict="dismissed"` → result list has one dismissed finding.
- `test_no_candidates_makes_no_llm_call` (L414): Empty environment → `decided == []` and `mock_provider.complete` never called.

### TestAnalyzerClass (L425–480)
Tests for `DeadParameterAnalyzer` class properties and `analyze_async` pipeline.

- `test_name` (L426): `analyzer.name == "dead_params"`.
- `test_cli_flag` (L430): `analyzer.cli_flag == "dead-params"`.
- `test_description` (L434): Description contains "dead" and "parameter".
- `test_category_mapping` (L439): Uses `finding_from_dead_param_candidate` + `dataclasses.replace` to produce confirmed/dismissed findings, patches `detect_dead_params_async`, runs `analyzer.analyze_async`. Asserts:
  - Only confirmed findings appear in `result.findings`.
  - `JunkFinding.category == "dead_parameter"`, `name == "func.unused"`, `reason == "Never passed"`, `line_start == 10`.
  - `metadata["gated_lines"] == []` (gated_lines phased out with per-detector verify tool, L474 comment).
  - `finding_id`, `verdict`, `total_candidates == 2`, `analyzer_name == "dead_params"`.

### TestScorecardIntegration (L485–518)
- `test_dead_param_findings_in_junk_metrics` (L486): Builds a `JunkAnalysisResult` with one `JunkFinding` (`line_start=20, line_end=30`), passes to `build_scorecard`. Asserts `sc.junk_total_lines == 11`, `"dead_params" in sc.junk_sources`, `sc.junk_by_category["dead_parameter"] == 1`.

### TestSameFileCaller (L522–618)
Tests for same-file call-site detection behavior.

- `test_same_file_caller_outside_definition_is_visible` (L524): A same-file call at line 9 (outside function definition lines 1–5) should appear as a `CallSite`.
- `test_same_file_match_inside_definition_is_excluded` (L576): A name match inside the function's own line range (line 5) should NOT be a call site; only the external same-file call (line 9) counts.

### TestConstructorPattern (L622–664)
- `test_class_constructor_call_is_detected` (L624): `ClassName(` call pattern in caller file matches `__init__` params. Optional `verbose` param detected as candidate with call site in `src/caller.py`.

## Key Invariants Tested
1. Only `visibility="public"` symbols with `optional: True` parameters that have importers become candidates.
2. Call-site collection is scoped to importer files only (prevents false positives from repo-wide name collisions).
3. Same-file call sites are included only when outside the function's own definition line range.
4. Dotted method names (`Class.method`) match instance-call patterns (`obj.method`).
5. Constructor calls (`ClassName(`) count as call sites for `__init__` params.
6. Zero candidates → zero LLM calls.
7. Only `verdict="confirmed"` findings pass through to `JunkFinding` output.

## Dependencies
- `osoji.deadparam`: `CallSite`, `DeadParamCandidate`, `DeadParameterAnalyzer`, `detect_dead_params_async`, `scan_dead_param_candidates`
- `osoji.config.Config`
- `osoji.junk`: `JunkAnalysisResult`, `JunkFinding`
- `osoji.llm.types`: `CompletionResult`, `ToolCall`
- `osoji.findings_adapter.finding_from_dead_param_candidate` (imported inside test at L443)
- `osoji.scorecard.build_scorecard` (imported inside test at L488)
- `pytest`, `pytest-asyncio` (async test support)
- `unittest.mock`: `AsyncMock`, `MagicMock`, `patch`

## Fixture Pattern
All filesystem-based tests use `temp_dir` (a session or function-scoped pytest fixture, not defined in this file — provided by conftest). The fixture provides a `pathlib.Path` to a temporary directory. Shadow/symbol/facts files are written under `.osoji/` subdirectories.