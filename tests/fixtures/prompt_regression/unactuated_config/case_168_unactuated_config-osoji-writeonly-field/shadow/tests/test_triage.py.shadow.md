# tests\test_triage.py
@source-hash: 088c2db55b509e9d
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:19Z

## Test Suite: Triage Stage (V1-3+)

Comprehensive test coverage for `osoji.triage` — the unified triage decision stage. Tests run fully offline using a `FakeProvider` mock; no network calls. Covers four primary scenarios: claim mode batch verdicts, exploration mode tool-calling loop, verdict cache short-circuiting, and insufficient-evidence escalation routing.

### Key Fixtures & Helpers

**`config` fixture (L22–24):** Returns a `Config(root_path=temp_dir, respect_gitignore=False)`. Depends on an external `temp_dir` fixture (not defined here — likely in `conftest.py`).

**`explore_repo` fixture (L301–306):** Creates a mini repo under `temp_dir/repo/src/x.py` containing `def old_helper()` with a `DISTINCTIVE-MARKER` return value; returns a `Config` scoped to that root.

**`make_finding(**overrides)` (L27–40):** Factory for `Finding` instances with a fixed debris/dead_code base (detector, path, lines, symbol, contract fields). Accepts keyword overrides. Default `symbol="old_helper"`.

**`FakeProvider` (L43–58):** Minimal async LLM provider mock. Queues pre-built `CompletionResult` objects and pops them in order per `complete()` call. Records all calls to `self.calls` for assertion. `close()` is a no-op.

**`verdicts_result(verdicts, *, in_tok, out_tok)` (L61–70):** Builds a `CompletionResult` with a single `submit_triage_verdicts` tool call containing the given verdicts list. Default 100 input / 40 output tokens.

**`tool_use_result(name, tool_input, *, call_id, in_tok, out_tok)` (L290–298):** Builds a `CompletionResult` with a single tool call of any name (used for exploration mode: `read_file`, `submit_triage_verdict`).

### Test Groups

#### Claim Mode (L76–166)
- **`test_claim_mode_fills_all_verdict_fields`** (L77–101): Verifies `decide_batch` in `"claim"` mode correctly maps all verdict fields (verdict, confidence, triage_reasoning, suggested_fix, severity) onto returned `Finding` objects, plus token counts and call count.
- **`test_claim_mode_maps_by_batch_index_not_finding_id`** (L105–126): Verifies batch_index disambiguation for duplicate-id findings (symbol=None collisions). Confirms index 0→dismissed, index 1→confirmed even when `finding.id` is identical.
- **`test_claim_mode_empty_batch_makes_no_call`** (L130–135): Empty claims list → no provider calls, empty findings.
- **`test_claim_mode_renders_evidence_into_prompt`** (L139–156): Evidence with a `cross_file_reference` kind containing a reference to `src/y.py` must appear in the user message content.
- **`test_claim_mode_uses_supplied_system_prompt`** (L160–166): `system_prompt="CUSTOM-RUBRIC"` passed to `decide_batch` propagates verbatim to `provider.complete(system=...)`.

#### Symbol-less Claims / Cross-wiring Guard (L169–217)
- **`test_symbolless_claim_renders_location_echo`** (L173–185): When `symbol=None`, the rendered user message must contain `Symbol: \`src/x.py:10\`` (path:line fallback identity).
- **`test_completeness_validator_catches_cross_wired_symbolless_claims`** (L189–217): Retrieves the `tool_input_validators[0]` function from `provider.calls[0]["options"]` and directly calls it to assert: swapped batch_index→symbol mappings produce 2 errors; correct alignment produces empty error list.

#### Evidence Rendering (L220–284)
Direct unit tests of the `_render_evidence` internal function:
- **`test_render_surrounding_code_evidence`** (L223–237): `surrounding_code` kind renders file, snippet, and enclosing symbol name; does not fall back to raw JSON.
- **`test_render_declared_intent_evidence`** (L240–250): `declared_intent` kind renders block label and text.
- **`test_render_zero_hit_scan_scope_states_absence`** (L253–263): Empty references list renders explicit "No references" with file count and needle names.
- **`test_render_export_surface`** (L266–274): `export_surface` payload produces output containing "export".
- **`test_render_shadow_doc_excerpt_payload`** (L277–284): `shadow_doc_claim` with `excerpt` field renders excerpt text.

#### Exploration Mode (L309–364)
- **`test_exploration_runs_tools_then_applies_verdict`** (L310–338): Two-turn loop: `read_file` tool call output fed back (asserted via `DISTINCTIVE-MARKER` in tool_result block), then `submit_triage_verdict` applies. Trace records both call names.
- **`test_exploration_uses_auto_tool_choice`** (L342–349): Verifies `options.tool_choice == {"type": "auto"}` in exploration mode.
- **`test_exploration_turn_limit_yields_uncertain`** (L353–364): Model repeatedly calls `read_file` without submitting verdict; after `_MAX_EXPLORATION_TURNS` (8) turns, verdict defaults to `"uncertain"`.

#### Verdict Cache (L370–406)
- **`test_cache_hit_short_circuits_llm`** (L371–388): Cache keyed `(finding.id, "fp-1")` prevents LLM call; returned finding uses cached values; `verdict_cache_hit_rate == 1.0`.
- **`test_none_fingerprint_is_cache_ineligible`** (L392–406): `evidence_fingerprint=None` findings are never served from cache even if `(id, None)` key exists; always go to LLM; `verdict_cache_hit_rate == 0.0`.

#### Escalation Routing (L409–443)
- **`test_insufficient_evidence_passes_through_by_default`** (L413–424): `Claim(..., insufficient_evidence=True)` with no escalation flag → no LLM call, `verdict` remains `None`, `would_escalate_count == 1`.
- **`test_insufficient_evidence_escalates_when_enabled`** (L428–443): Same claim with `escalate_insufficient=True` → runs exploration mode, sets verdict, `would_escalate_count == 1`, `exploration_traces` has one entry.

#### Decided-Findings Ledger (L446–485)
- **`test_decide_batch_appends_decided_findings_to_ledger`** (L450–467): When `config.decided_ledger = []` is pre-attached, completed verdicts are appended as dicts with `symbol`, `verdict`, `id` keys.
- **`test_decide_batch_without_ledger_attached_does_not_crash`** (L471–485): When `config` has no `decided_ledger` attribute (normal test case), `decide_batch` completes without error.

### Architectural Notes
- The `_MAX_EXPLORATION_TURNS` constant (value: 8) is asserted at L364 by checking `len(provider.calls) == 8`.
- Tool input validator is accessed as `provider.calls[0]["options"].tool_input_validators[0]` — implies `options` is an object with a `tool_input_validators` list attribute.
- Cache keys are `(finding.id, evidence_fingerprint)` tuples; `None` fingerprint is explicitly non-cacheable.
- `result.exploration_traces` is a list of dicts with a `"calls"` key containing dicts with `"name"` fields.
- `config.decided_ledger` is an optional runtime attribute set by the audit orchestrator, not part of the base `Config` schema.