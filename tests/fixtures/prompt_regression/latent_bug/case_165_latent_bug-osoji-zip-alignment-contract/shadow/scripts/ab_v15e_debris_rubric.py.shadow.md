# scripts\ab_v15e_debris_rubric.py
@source-hash: 11d191a6e7971c3b
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:43Z

## Purpose

A/B evaluation script (issue osojicode/work#52) that replays the `.osoji/findings/` debris corpus through two different triage system prompts to measure verdict divergence when migrating from the legacy `DEBRIS_TRIAGE_SYSTEM_PROMPT` to the new unified `TRIAGE_SYSTEM_PROMPT`.

## Architecture

- **Side A (legacy)**: Uses the frozen `DEBRIS_TRIAGE_SYSTEM_PROMPT` (L45–68), a copy of the retired prompt removed from `triage.py` at V1-5e.
- **Side B (unified)**: Uses the imported `TRIAGE_SYSTEM_PROMPT` from `osoji.triage` (L41).
- Both sides receive identical claims, evidence, and code; only the system prompt differs.
- Bypasses the impl-hash staleness gate via `load_debris_ignoring_impl_hash` (imported from `measure_debris_cutover.py`, L71).

## Key Symbols

### `DEBRIS_TRIAGE_SYSTEM_PROMPT` (L45–68)
Frozen string constant — inline copy of the legacy debris triage prompt that was removed from `triage.py` at V1-5e. Preserved here so the A/B script remains runnable as a historical artifact after the production flip.

### `_finding_row(finding)` (L74–88)
Internal helper. Serializes a finding object to a flat dict with keys: `id`, `detector`, `path`, `symbol`, `line_start`, `line_end`, `contract_claim`, `verdict`, `confidence`, `severity`, `reasoning` (mapped from `triage_reasoning`), `suggested_fix`.

### `_run_side(label, claims, config, system_prompt)` (L91–123)
Async function. Runs triage for one A/B side:
1. Imports `decide_junk_claims` from `osoji.junk_triage` (L103, deferred import).
2. Creates an LLM provider via `create_runtime(config)` (L105).
3. Calls `decide_junk_claims` with the given system prompt (L107–109).
4. Closes the provider (L111).
5. Returns dict with `input_tokens`, `output_tokens`, `undecided`, `findings` (list of `_finding_row` dicts).

Chunked via `decide_junk_claims` (BATCH_SIZE=12, bisect on failure) rather than a single `decide_batch` call — motivated by a run-1 off-by-one misalignment on side B described in ab-v15e-report.md (docstring L92–101).

### `main()` (L126–183)
CLI entry point:
1. Parses `--root` (required) and `--out` (default `scratch/ab-v15e-raw.json`) (L127–130).
2. Loads `.env` from root (L132).
3. Constructs `Config` with `provider="anthropic"`, `respect_gitignore=False`, `quiet=True` (L134–139).
4. Loads corpus via `load_debris_ignoring_impl_hash` (L140).
5. Builds claims via `build_debris_claims` (L141).
6. Runs both sides sequentially with `asyncio.run` (L150–151).
7. Compares verdicts pairwise (L153–166) using `assert row_a["id"] == row_b["id"]` (L155) — assumes identical ordering between sides.
8. Writes JSON output with keys: `corpus_size`, `would_escalate`, `changed_verdict_count`, `changed`, `side_a_legacy`, `side_b_unified` (L168–178).
9. Prints per-changed-finding summary to stdout (L180–182).

## Path Setup

- `REPO_ROOT` (L33): parent of `scripts/` directory.
- `src/` added to `sys.path` (L34) for `osoji.*` imports.
- `scripts/` added to `sys.path` (L70) for `measure_debris_cutover` import.

## Notable Patterns / Constraints

- The `assert` at L155 will raise `AssertionError` (not a graceful error) if the two sides return findings in different order. This is a correctness invariant, not a latent bug.
- The deferred import of `decide_junk_claims` inside `_run_side` (L103) avoids circular imports or import-time side effects.
- Both sides are run sequentially (not concurrently) to avoid LLM rate-limit contention.
- Output directory is created with `mkdir(parents=True, exist_ok=True)` (L177) before write.
