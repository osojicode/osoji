# tests\test_junk_reachability_cutover.py
@source-hash: 361a88732078b008
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:00Z

## Purpose
Cutover gate tests for the V1-5a migration of dead-code/dead-param detection onto the unified Triage pipeline. These mock-equivalence tests use a canned LLM provider (`FakeProvider`) to pin behavioral contracts that the migration must preserve or deliberately change.

## Key Behavioral Contracts Under Test

### Verdict Polarity (vs debris suppression)
- `confirmed` → reported as a finding
- `dismissed` / `uncertain` / `undecided` → dropped (not reported)

### AST Fast Path (L127–138, L141–159)
- `test_ast_clean_zero_confirms_without_llm`: If AST facts are clean (no string-literal hits), mechanical confirmation fires — **zero LLM calls**, `confidence_source="ast_proven"`, `confidence=1.0`.
- `test_ast_string_literal_hit_demotes_to_triage`: A quoted string match (e.g. `getattr(lib, "dead_func")`) demotes the AST-proven candidate to Triage; the rendered claim includes `[match is inside a quoted string]` positional marker; `dismissed` verdict → finding dropped.

### Prompt Identity (L162–180)
- `test_unified_rubric_prompt_identity`: Non-AST facts (`extraction_method="llm"`) force the LLM route; asserts `provider.last_system == TRIAGE_SYSTEM_PROMPT` (unified prompt, not legacy per-detector prompts).

### Verdict Filtering (L183–207)
- `test_uncertain_and_dismissed_are_dropped`: Both `uncertain` and `dismissed` verdicts result in `result.findings == []`; `result.total_candidates == 2` still tracks them.

### Chunking (L229–239)
- `test_claims_split_into_bounded_chunks`: 13 claims split into `[12, 1]` batches; all 13 returned as `confirmed`.

### Failure Handling / Bisection (L242–255)
- `test_failing_chunk_bisects_then_keeps_claims_undecided`: On error, a chunk bisects once; both halves fail → 3 total provider calls, all 4 claims returned with `verdict is None`, tokens `(0, 0)`.

### Symbol Echo Validation (L258–292)
- `test_symbol_echo_mismatch_is_a_validation_error`: Cross-wired verdicts (wrong `symbol` field for a `batch_index`) produce 2 validation errors containing `"re-check"`; aligned verdicts produce no errors.

### Verdict Cache / VerdictSession (L295–366)
- `test_session_cache_hits_skip_llm_and_are_counted` (L312–331): Pre-populated session cache → 0 LLM calls; `session.claims_seen==2`, `session.cache_hits==2`, `session.hit_rate==1.0`.
- `test_session_harvests_fresh_verdicts` (L334–354): Empty session cache → 1 LLM call; harvested entries include `verdict`, `evidence_fingerprint`, `detector=="deadcode:dead_symbol"`.
- `test_no_session_leaves_behavior_unchanged` (L357–366): No session on config → normal LLM flow, unchanged behavior.

## Key Helpers

### `_write(temp_dir, rel, text)` (L36–39)
Writes a file into `temp_dir`, creating parent directories.

### `_write_symbols(temp_dir, source, symbols)` (L42–52)
Writes a `.osoji/symbols/{source}.symbols.json` fixture with fixed `source_hash="abc"` and `file_role="service"`.

### `_write_facts(temp_dir, source, ...)` (L55–70)
Writes a `.osoji/facts/{safe}.facts.json` fixture. Replaces `/` with `__` in the filename. `extraction_method` defaults to `"ast"`.

### `FakeProvider` (L73–109)
Async LLM provider stub:
- Records `calls`, `last_system`, `last_user`, `batch_sizes`.
- On `complete()`: introspects claim count via `options.tool_input_validators[0]("submit_triage_verdicts", {"verdicts": []})`, pops from `_verdicts_per_call` list or auto-generates `confirmed` verdicts for all batch indices.
- If `_error` is set, raises it unconditionally.
- Returns `CompletionResult` with a single `ToolCall(name="submit_triage_verdicts")`.

### `_ast_dead_symbol_env(temp_dir)` (L112–120)
Shared fixture: creates `src/lib.py` with `dead_func`, writes matching symbols and full-AST facts with `dead_func` as an export.

### `_trivial_claims(config, n)` (L213–225)
Builds `n` minimal `JunkClaim` objects via `DeadCodeCandidate` → `finding_from_dead_code_candidate` → `build_junk_claims`. Uses empty `BuildContext` (no facts_db, no symbols).

### `_session_cache_for(claims)` (L298–309)
Builds a pre-populated verdict cache dict keyed by `(finding.id, finding.evidence_fingerprint)` for use with `VerdictSession(cache=...)`.

### `ProbingProvider` (L267–284, inside test)
Inner subclass of `FakeProvider` that runs the validator against both crossed and aligned verdict payloads, capturing errors in `captured` dict, then delegates to `super().complete()`.

## Key Dependencies
| Import | Usage |
|---|---|
| `Config` | Root config object; `config.verdict_session` is set directly in cache tests |
| `DeadCodeAnalyzer` | End-to-end analyzer under test |
| `BuildContext` | Required by `build_junk_claims`; constructed with `facts_db=None` |
| `finding_from_dead_code_candidate` | Converts `DeadCodeCandidate` to a finding |
| `build_junk_claims`, `decide_junk_claims` | Core junk triage pipeline functions under test |
| `CompletionResult`, `ToolCall` | LLM response types used in `FakeProvider` |
| `TRIAGE_SYSTEM_PROMPT` | Asserted as the exact system prompt passed to provider |
| `VerdictSession` | Session-level verdict cache; imported lazily inside tests |
| `DeadCodeCandidate` | Imported lazily inside `_trivial_claims` |

## Notable Patterns
- **Lazy imports** inside test functions for `VerdictSession` and `DeadCodeCandidate` (L214, L314, L336).
- **`config.verdict_session` attribute write** (L320, L342) — config is mutated post-construction; cross-file contract with `Config` class.
- **Validator introspection**: `FakeProvider.complete` calls `options.tool_input_validators[0]("submit_triage_verdicts", {"verdicts": []})` to determine batch size from the validator's side-effect return value (L91–92). This is unusual — the validator returns the list of claims it would validate.
- **`temp_dir` fixture** — assumed to be provided by conftest (not defined here), yielding a `pathlib.Path`.
- All tests are `@pytest.mark.asyncio`.
