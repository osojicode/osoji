# tests\test_doc_analysis_cutover.py
@source-hash: 6102c1e73f930f63
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:06Z

## Purpose
Cutover gate test suite for V1-5d: validates that `doc_analysis` integrates with the unified Triage pipeline (work#31), replacing the old per-doc verify pass. Pins verdict routing, prompt identity, shadow scope selection, and schema reconciliation behaviors that the migration must preserve or deliberately change.

## Key Invariants Being Tested
1. **Verdict routing**: `confirmed` → kept; `dismissed` → suppressed (removed from findings); `uncertain` → kept but severity downgraded to `"warning"` with `triage_reasoning` attached; LLM/chunk failure → findings kept unverified (`verdict=None`).
2. **Prompt identity**: `_triage_doc_findings` must use `TRIAGE_SYSTEM_PROMPT` (unified triage), NOT the deleted per-doc verify prompt.
3. **Shadow scope**: local-drift doc findings get file-scope shadow evidence; cross-directory claims get root scope; single-directory multi-file gets directory scope.
4. **Schema reconciliation**: the four doc categories (`stale_content`, `incorrect_content`, `misleading_claim`, `obsolete_reference`) are unprefixed explicit `CLAIM_BUILDER_SCHEMA` keys resolving to `gap_type="description"`.
5. **Debris classification exclusion**: `process_artifact` classified results are NOT triaged (no LLM call made).
6. **Triage failure recording**: triage post-pass failures must call `config.audit_degradations.append({"phase": "doc-triage", "error": ...})`.

## Key Components

### `FakeProvider` (L49–85)
Canned LLM provider simulating `submit_triage_verdicts`. Tracks `calls`, `last_system`, `last_user`. Accepts `verdicts_per_call` (list of verdict batches, consumed in order) or `error` (raises on `complete()`). Uses `options.tool_input_validators[0]` to determine batch size and auto-generates `"confirmed"` verdicts if `verdicts_per_call` is `None`. Implements `async complete(messages, system, options)` and `async close()`.

### `_FakeAnalyzeProvider` (L244–264)
Canned provider for `analyze_docs_async` integration test. Returns a fixed `analyze_document` tool call with empty findings and `classification="reference"`. Used only in `test_triage_post_pass_failure_records_doc_triage_degradation`.

### Helper: `_doc_finding(**over)` (L88–99)
Constructs a `DocFinding` with sensible defaults (`category="incorrect_content"`, `severity="error"`, `shadow_ref="src/cli.py"`, etc.) and applies keyword overrides.

### Helper: `_result_with(temp_dir, findings, ...)` (L102–113)
Constructs a `DocAnalysisResult` for `README.md` (default), writes the doc file to disk so `SurroundingCodeBuilder` can satisfy the `require_any` gate. Returns `DocAnalysisResult` with `classification="reference"` (default).

### Helper: `_shadow_evidence(claim)` (L337–338)
Filters `claim.finding.evidence` for entries with `kind == "shadow_doc_claim"`.

### Helper: `_write(temp_dir, rel, text)` (L43–46)
Creates parent directories and writes a UTF-8 file into `temp_dir`.

## Test Functions

| Test | Lines | What It Pins |
|------|-------|-------------|
| `test_confirmed_findings_ship` | L120–136 | confirmed kept, dismissed removed; filter operates per finding |
| `test_confirmed_finding_carries_suggested_fix_and_finding_id` | L139–155 | `suggested_fix` and `finding_id` propagated from decided Finding |
| `test_dismissed_suppresses` | L158–168 | single dismissed → empty findings list |
| `test_llm_failure_keeps_findings` | L171–183 | on LLM error, both findings survive with `verdict=None` |
| `test_uncertain_kept_as_warning_with_reasoning` | L186–202 | uncertain → `severity="warning"`, `triage_reasoning` contains reasoning text |
| `test_confirmed_verdict_can_regrade_severity` | L205–217 | confirmed verdict can override `severity` field |
| `test_no_findings_makes_no_llm_call` | L220–229 | empty findings → 0 LLM calls, returns `(0, 0)` tokens |
| `test_debris_result_findings_are_not_triaged` | L232–241 | `process_artifact` classification bypasses triage entirely |
| `test_triage_post_pass_failure_records_doc_triage_degradation` | L267–282 | triage failure records `{"phase": "doc-triage", "error": "boom"}` in `config.audit_degradations` |
| `test_cutover_uses_unified_triage_prompt` | L285–295 | `last_system == TRIAGE_SYSTEM_PROMPT`; contains sentinel text |
| `test_coverage_dismissed_accuracy_confirmed` | L298–331 | accuracy/coverage boundary: coverage "does not mention" → dismissed; accuracy contradiction → confirmed |
| `test_doc_finding_gets_file_scope_not_root` | L341–360 | file-scope shadow evidence selected; root scope excluded |
| `test_doc_finding_single_dir_multi_file_gets_directory_scope` | L363–381 | directory-scope shadow for single-directory multi-file finding |
| `test_doc_finding_multi_dir_gets_root_scope` | L384–401 | cross-directory claim → root-scope shadow evidence |
| `test_doc_categories_resolve_to_description_schema` | L407–414 | all 4 doc categories in `CLAIM_BUILDER_SCHEMA`, `gap_type_for(cat) == "description"`, `category_of(finding) == cat` (unprefixed) |

## Dependencies
- `osoji.doc_analysis`: `DocAnalysisResult`, `DocFinding`, `_triage_doc_findings` (private, imported directly), `analyze_docs_async`
- `osoji.claim_builder`: `CLAIM_BUILDER_SCHEMA`, `build_claims`, `category_of`
- `osoji.config`: `Config`
- `osoji.evidence_builders`: `BuildContext`
- `osoji.findings_adapter`: `finding_from_doc`, `gap_type_for`
- `osoji.llm.types`: `CompletionResult`, `ToolCall`
- `osoji.triage`: `TRIAGE_SYSTEM_PROMPT`

## Architectural Notes
- Tests import `_triage_doc_findings` (private) directly — intentional for cutover gate granularity.
- `FakeProvider.complete` reads batch size from `options.tool_input_validators[0]` calling it with `"submit_triage_verdicts"` and empty verdicts dict (L65–66); this mirrors the real triage call contract.
- `config.audit_degradations` is set to `[]` before the integration test (L275) — must exist as an attribute on `Config` for the degradation recording test.
- `_result_with` writes the doc file to disk (L105) because evidence builders require real files; without it the claim would not be decided.
- The sentinel string `"single verifier for every code-quality finding"` (L295) is asserted to be present in `TRIAGE_SYSTEM_PROMPT`, providing a stable identity pin.