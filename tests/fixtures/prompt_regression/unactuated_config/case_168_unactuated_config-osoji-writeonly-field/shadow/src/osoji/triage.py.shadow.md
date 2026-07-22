# src\osoji\triage.py
@source-hash: b904fa7ef37f5348
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:23Z

## Unified Triage Stage (V1-3+)

**Primary Purpose:** Single evidence-weighted LLM verifier that decides verdicts for code-quality findings (Claims). Replaces six+ scattered per-detector verification gates. Fills `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity`, and `contract_class` on each `Finding`.

---

### Architecture Overview

Two operating modes:
- **claim mode** (default): One batched, forced-tool LLM call decides all non-cache, non-escalated claims. Production path.
- **exploration mode**: Per-claim multi-turn loop with read-only tools (`read_file`, `grep`, `list_dir`). Used by Claim-Builder bootstrap and per-claim escalation.

**Incremental-audit cache (V1-9):** `decide_batch` accepts `verdict_cache: dict[tuple[str, str], dict]` keyed by `(finding.id, evidence_fingerprint)`. Cache hits skip the LLM entirely. `None` fingerprint = always triaged (never a key).

---

### Key Constants

**`TRIAGE_PROMPT_SECTIONS`** (L63–249): Ordered dict of named rubric sections. Sections: `mission`, `predicates`, `significance`, `reachability_weighing`, `parameter`, `unactuated_config`, `vendored_material`, `orphaned_file`, `dead_cicd`, `contract_literal_classes`, `contract_verdict`, `contract_bundles`, `contract_ecosystem_boundary`, `prose_doc_gaps`, `closing`. Supports leave-one-out ablations via `render_triage_prompt(omit=...)`.

**`TRIAGE_SYSTEM_PROMPT`** (L251): Concatenation of all `TRIAGE_PROMPT_SECTIONS` values. The canonical unified rubric. Every production Triage path passes it since V1-5e.

**`_MAX_EXPLORATION_TURNS`** (L298): Hard ceiling of 8 turns per exploration claim. Reaching it yields `uncertain` verdict.

---

### Key Symbols

**`render_triage_prompt(omit)`** (L254–265): Assembles rubric with named sections omitted. Raises `ValueError` on unknown section names (typo guard).

**`Claim`** (L269–282): Thin dataclass — `finding: Finding` + `insufficient_evidence: bool = False`. The Evidence lives on `finding.evidence`. `insufficient_evidence` marks claims the Claim Builder couldn't fill; Triage escalates only when `escalate_insufficient=True`.

**`TriageBatchResult`** (L284–293): Batch outcome dataclass with `findings: list[Finding]`, `input_tokens`, `output_tokens`, `verdict_cache_hit_rate: float`, `would_escalate_count: int`, `exploration_traces: list[dict]`.

**`_claim_echo(finding)`** (L301–313): Identity token for cross-wiring guard. Returns `finding.symbol` if present, else `path:line_start`, else `path`. Used to validate verdict-to-claim alignment in batches.

**`Triage`** (L316–606): Main class.
- `__init__(config, rate_limiter, *, executor, provider)` (L323–334): Provider injection for tests; defaults to `ExplorationExecutor(config)` for executor.
- `decide_batch(claims, *, mode, system_prompt, verdict_cache, escalate_insufficient)` (L336–424): Main entry point. Routes claims through cache → claim_route or explore_route. Attaches decided findings to optional `config.decided_ledger` (L412–414).
- `_get_provider()` (L428–434): Returns `(provider, owns_it)`. Injected providers are not closed.
- `_run_claim_batch(claims, system_prompt, provider)` (L438–497): Single batched LLM call with forced `submit_triage_verdicts` tool. Includes `check_completeness` validator (L444–465) that enforces every batch_index has a verdict and symbol echo matches.
- `_render_claim_batch(claims)` (L499–508): Formats all claims as markdown with batch indices.
- `_render_claim_block(index, finding)` (L510–524): Static method. Renders one claim block: detector, gap_type, location, symbol echo, claim, observed behavior, evidence.
- `_run_exploration(claim, system_prompt, provider)` (L528–606): Multi-turn exploration loop. Returns `(Finding, input_tokens, output_tokens, trace_dict)`. Turn limit yields `verdict="uncertain"`.

**`_apply_verdict(finding, v)`** (L612–623): Returns `Finding` copy with verdict fields from LLM verdict dict. Keys: `verdict`, `confidence`, `reasoning` (→`triage_reasoning`), `suggested_fix`, `severity`, `contract_class`.

**`_apply_cached(finding, cached)`** (L626–637): Returns `Finding` copy from cache entry. Note: cache key is `triage_reasoning` (vs LLM's `reasoning` in `_apply_verdict`).

**`_render_evidence(ev)`** (L640–734): Renders `Evidence` objects into human-readable prompt text. Dispatches on `ev.kind`: `cross_file_reference`, `surrounding_code`, `declared_intent`, `type_signature`, `shadow_doc_claim`. Falls back to `json.dumps(ev.payload)`.

---

### Routing Logic in `decide_batch`

```
for each claim:
  if fingerprint is not None and (id, fp) in cache → cache hit
  elif mode == "exploration" → explore_route
  elif claim.insufficient_evidence:
    if escalate_insufficient → explore_route
    else → pass-through (verdict stays None)
  else → claim_route (batched LLM)
```

claim_route → `_run_claim_batch` (one call for all)
explore_route → `_run_exploration` per claim (sequential)

---

### Tool Integration

- Claim mode forces `submit_triage_verdicts` tool (via `get_triage_claim_tool_definitions()`).
- Exploration mode uses `auto` tool_choice with `get_triage_exploration_tool_definitions()` (read_file, grep, list_dir + submit_triage_verdict singular).
- `max_tokens = max(1024, n * 500)` for claim batches (L477).
- `reservation_key="audit.triage"` / `"audit.triage.explore"` for rate limiting.

---

### Cross-file Relationships

- `Config.model_for("medium")`: model tier used for all LLM calls.
- `Config.decided_ledger` (optional attribute): orchestrator-attached list; decided findings are serialized and appended via `f.to_dict()`.
- `Finding.evidence_fingerprint`, `Finding.id`: cache key components.
- `ExplorationExecutor.run(tool_name, tool_input)`: dispatches tool calls in exploration turns.
- `create_runtime(config, rate_limiter)`: creates LLM provider when none injected.

---

### Notable Patterns

- `dataclasses.replace()` used throughout for immutable Finding updates.
- Completeness validator (`check_completeness`) is a closure over `n` and `claims`, passed as `tool_input_validators` — enforces batch coverage at the LLM protocol level.
- Symbol echo guard (L457–464): catches off-by-one verdict-to-claim assignments for sibling claims.
- `_apply_verdict` uses key `"reasoning"` while `_apply_cached` uses key `"triage_reasoning"` — intentional asymmetry reflecting LLM output schema vs. cache storage schema.
