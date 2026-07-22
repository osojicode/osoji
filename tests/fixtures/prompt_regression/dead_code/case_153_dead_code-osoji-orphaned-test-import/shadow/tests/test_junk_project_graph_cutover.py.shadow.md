# tests\test_junk_project_graph_cutover.py
@source-hash: d8ecb0adb588186f
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:13Z

## Purpose

Cutover gate test suite for V1-5b (osojicode/work#29): validates that the four junk analyzers (`DeadPlumbingAnalyzer`, `OrphanedFilesAnalyzer`, `DeadDepsAnalyzer`, `DeadCICDAnalyzer`) correctly operate on the **unified Triage pipeline** rather than any per-detector legacy verify tools.

## Key Concepts

### FakeProvider (L78-127)
Routing fake LLM provider. Routes `complete()` calls by `options.tool_choice['name']`:
- **Proposal tools** (e.g., `extract_obligations`, `identify_entry_points`, `resolve_import_names`, `classify_deps`, `identify_relationships`): Returns canned payloads from `self.proposals` dict.
- **`submit_triage_verdicts`**: Returns canned `self._triage_verdicts` (or auto-generates all-confirmed verdicts by querying `options.tool_input_validators[0]` to determine batch count). Records `last_system` and `last_user` from the call.
- **Assertion on construction**: Any call requesting a tool in `_LEGACY_VERIFY_TOOLS` raises `AssertionError` immediately (L97-99).

### `_LEGACY_VERIFY_TOOLS` (L70-75)
Set of deleted per-detector verify tool names: `verify_actuation`, `verify_orphan_files`, `verify_dead_deps`, `verify_dead_cicd`. Used as a guard inside `FakeProvider.complete()` and in `_assert_unified_prompt()`.

### `_assert_unified_prompt(provider)` (L130-133)
Helper that pins three invariants:
1. Exactly one triage call was made.
2. `provider.last_system == TRIAGE_SYSTEM_PROMPT` (unified prompt, not per-detector prompts).
3. No legacy verify tool was served.

## Environment Helpers

- `_write(temp_dir, rel, text)` (L36-39): Creates a file at `temp_dir/rel` with given text content.
- `_write_symbols(temp_dir, source, symbols, file_role="service")` (L42-52): Writes a `.osoji/symbols/<source>.symbols.json` with schema `{source, source_hash, file_role, symbols}`.
- `_write_signature(temp_dir, source, purpose, topics, public_surface)` (L55-65): Writes a `.osoji/signatures/<source>.signature.json`.
- `_orphan_env(temp_dir)` (L183-196): Sets up a minimal 3-file environment: `src/main.py` (entry), `src/orphan_a.py`, `src/orphan_b.py` — no import edges between them.

## Test Cases

### `test_plumbing_confirmed_survives_dismissed_dropped` (L140-177)
- Fixture: TypeScript schema file with `taskTimeoutMs` and `turnTimeoutMs` fields; runner file referencing both.
- Proposal tool: `extract_obligations` → 2 obligations.
- Triage verdicts: `confirmed` for `taskTimeoutMs`, `dismissed` for `turnTimeoutMs`.
- Assertions: 1 finding (`taskTimeoutMs`), category=`unactuated_config`, kind=`config_field`, confidence=0.9, remediation=`"add timer"`, `metadata["schema_name"]=="Schema"`, `confidence_source=="llm_inferred"`.

### `test_orphan_confirmed_survives_dismissed_dropped` (L200-231)
- Uses `_orphan_env`. Proposal tools: `identify_entry_points` (main=entry, orphan_a/b=non-entry), `identify_relationships` (empty).
- Triage verdicts: `confirmed` for `orphan_a.py`, `uncertain` for `orphan_b.py`.
- Assertions: 1 finding (`orphan_a.py`), category=`orphaned_file`, kind=`file`, `source_path=="src/orphan_a.py"`, remediation=`"delete it"`.

### `test_deps_confirmed_survives_dismissed_dropped` (L238-275)
- Fixture: `requirements.txt` with `dead-one` and `dead-two`; `src/app.py` importing nothing.
- Proposal tools: `resolve_import_names` (both as genuine candidates), `classify_deps` (both `genuine_candidate`).
- Triage verdicts: `confirmed` for `dead-one`, `dismissed` for `dead-two`.
- Assertions: 1 finding (`dead-one`), category=`dead_dependency`, kind=`dependency`, `source_path=="requirements.txt"`, confidence=0.85, `metadata["usage_type"]=="unused"`.

### `test_cicd_confirmed_survives_dismissed_dropped` (L282-311)
- Fixture: `Makefile` with `deploy` and `publish` targets referencing missing scripts.
- No proposal tool (Makefile parsed mechanically). `cicd_files` passed explicitly for determinism (L301-302).
- Triage verdicts: `confirmed` for `deploy`, `dismissed` for `publish`.
- Assertions: 1 finding (`deploy`), category=`dead_cicd`, kind=`makefile_target`, `source_path=="Makefile"`, confidence=0.85.

## Architectural Invariants Pinned by Tests

- **Confirmed → reported; dismissed/uncertain → dropped** (inverted vs debris suppression; candidates are hypotheses).
- **Unified prompt**: All four analyzers must use `TRIAGE_SYSTEM_PROMPT`, not per-detector verify prompts.
- **No legacy verify tools**: The unified pipeline must never invoke the four deleted verify tool names.
- **Finding re-wrapping**: A confirmed hypothesis produces a properly typed `JunkFinding` with correct `category`/`kind`/`name`.

## Dependencies

- `osoji.config.Config`: Project configuration, `root_path` and `respect_gitignore`.
- `osoji.junk_cicd.DeadCICDAnalyzer`: Makefile/CI target dead code analyzer.
- `osoji.junk_deps.DeadDepsAnalyzer`: Dead/unused dependency analyzer.
- `osoji.junk_orphan.OrphanedFilesAnalyzer`: Orphaned file analyzer.
- `osoji.llm.types.CompletionResult`, `ToolCall`: LLM response types.
- `osoji.plumbing.DeadPlumbingAnalyzer`: Unactuated config/schema analyzer.
- `osoji.triage.TRIAGE_SYSTEM_PROMPT`: The unified triage system prompt constant (verified at L132).
- `pytest.mark.asyncio`: All test functions are async.
- `temp_dir` fixture: Provided externally (likely `conftest.py`) as a `pathlib.Path` temporary directory.
