# scripts\ab_v159_significance_grade.py
@source-hash: 73191c365b90df9b
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:45Z

## Purpose

Experimental A/B harness (`work#59`) that replays the live `.osoji/findings/` debris corpus through the Triage stage twice to compare two rubric variants:
- **Side A**: `THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT` — frozen pre-work#59 rubric (TP = Reality + Significance + Actionability; dismiss on any failure)
- **Side B**: `TRIAGE_SYSTEM_PROMPT` — new ruled rubric (TP = Reality + Actionability; Significance grades severity, real-but-minor → info)

Also supports a `--control` mode that runs Side A's prompt twice (same prompt, same chunking) to measure sampling variance before interpreting A/B deltas (per wiki decisions/0016, decision 6).

## Key Symbols

### `THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT` (L54–198)
Large string constant containing the complete frozen pre-work#59 triage system prompt. Embedded directly in this file so the gate script remains runnable after `triage.py` changes the live rubric. Covers: three-predicate TP definition, reachability/contract/description-gap guidance, contract_class taxonomy.

### `_finding_row(finding)` (L204–218) — internal
Serialises a finding object to a plain dict for JSON output. Accesses fields: `id`, `detector`, `path`, `symbol`, `line_start`, `line_end`, `contract_claim`, `verdict`, `confidence`, `severity`, `triage_reasoning` (mapped to key `"reasoning"`), `suggested_fix`.

### `_run_side(label, claims, config, system_prompt)` (L221–247) — internal async
Runs `decide_junk_claims` for one side of the experiment. Creates and closes an LLM provider around the call. Returns a summary dict with token counts, verdict/severity counters, and serialised findings. Prints a one-line progress summary per side.

### `main()` (L250–328) — public entry point
CLI orchestrator:
1. Parses `--root`, `--out`, `--control` args (L251–259)
2. Loads `.env` from `--root` (L261)
3. Constructs `Config` with `provider="anthropic"`, `respect_gitignore=False`, `quiet=True` (L263–268)
4. Loads corpus via `load_debris_ignoring_impl_hash` and builds claims via `build_debris_claims` (L269–270)
5. Runs both sides sequentially via `asyncio.run` (L280–285)
6. Computes changed-verdict diff and identifies `demotions` (A dismissed → B confirmed@info) (L288–306)
7. Writes JSON result to `--out` (default `scratch/ab-v159-raw.json`) (L308–320)
8. Prints summary to stdout (L321–328)

## Architecture Notes

- **Script pattern**: Adds both `REPO_ROOT/src` and `REPO_ROOT/scripts` to `sys.path` at module level (L41–42, L200) to resolve sibling script imports (`measure_debris_cutover`) and `osoji` package imports without installation.
- `decide_junk_claims` is imported inside `_run_side` (L224) — deferred import to avoid import-time side effects.
- Provider is created and explicitly closed per side (L226–232) — clean async resource management.
- Verdict diff uses `zip` over ordered finding lists and `assert row_a["id"] == row_b["id"]` (L290–291) to enforce alignment; order must be stable across both sides.
- The `changed` list and `demotions` sublist (A=dismissed, B=confirmed, B.severity=info) are the primary adjudicable signals (L288–306).
- Output JSON schema (L308–317): `mode`, `corpus_size`, `would_escalate`, `changed_verdict_count`, `dismissed_to_confirmed_info_count`, `changed[]`, plus per-side keys named by `labels` tuple.

## Dependencies

| Import | Role |
|---|---|
| `osoji.claim_builder.build_debris_claims` | Converts raw debris findings to triage claims |
| `osoji.config.Config` | Project configuration object |
| `osoji.llm.runtime.create_runtime` | Creates LLM provider |
| `osoji.triage.TRIAGE_SYSTEM_PROMPT` | Live (post-work#59) triage system prompt (Side B) |
| `osoji.junk_triage.decide_junk_claims` | Batch triage decision engine (imported lazily inside `_run_side`) |
| `measure_debris_cutover.load_debris_ignoring_impl_hash` | Loads raw debris corpus ignoring impl hash mismatches |
| `dotenv.load_dotenv` | Loads API keys from `--root/.env` |

## Critical Constraints

- Finding order must be identical across both sides for the `zip`-based diff to be valid (L290).
- `THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT` is intentionally a frozen snapshot — do not sync it with `triage.py` changes.
- The script is designed for one-off experimental use, not production pipeline integration.
