# scripts\triage_bootstrap.py
@source-hash: a93de0ddefb9c4f2
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:12Z

## Purpose

Bootstrap harness for the V1-4 Claim Builder (osojicode/work#27). Runs the unified Triage stage over a curated bootstrap set (`tests/fixtures/bootstrap/manifest.json`) in four modes: `explore`, `explore-sdk`, `claim`, and `build`. Produces per-claim verdict/trace JSON files and a run summary under `tests/fixtures/bootstrap/traces/`.

---

## Modes

| CLI command    | `mode` string       | LLM used | Description |
|----------------|---------------------|----------|-------------|
| `explore`      | `"exploration"`     | Yes      | Evidence stripped; LLM must retrieve everything via tools |
| `explore-sdk`  | `"exploration-sdk"` | Yes      | Same as explore but uses Claude Agent SDK for MCP transport |
| `claim`        | `"claim"`           | Yes      | Mechanized Claim Builder fills evidence first, then triage |
| `build`        | `"build"`           | No       | Zero-LLM dry run; only runs Claim Builder to verify fill |

---

## Key Constants (L57–L66)

- `REPO_ROOT` (L57): Resolved repo root (two levels above `scripts/`)
- `BOOTSTRAP_DIR` (L64): `tests/fixtures/bootstrap/`
- `DEFAULT_MANIFEST` (L65): `tests/fixtures/bootstrap/manifest.json`
- `DEFAULT_TRACE_DIR` (L66): `tests/fixtures/bootstrap/traces/`

---

## Functions

### `load_manifest(path)` (L69–L75)
Reads and validates `manifest.json`. Ensures each entry has `slug`, `category`, `adjudicated_verdict`, and `finding` keys. Returns raw `dict`.

### `entries_to_claims(entries, *, strip_evidence)` (L78–L87)
Converts manifest entries to `Claim` objects. When `strip_evidence=True`, replaces `evidence=[]` via `dataclasses.replace` so explore-mode baselines see no pre-assembled evidence.

### `summarize(entries, findings)` (L90–L125)
Computes per-category agreement stats vs. adjudicated labels. Returns dict with `n`, `accuracy`, `accuracy_nongray`, `gray_count`, `per_category`, and `rows`. The `gray` field on entries marks ambiguous cases excluded from `accuracy_nongray`.

### `_stage_fixture_root(fixture_root, tmp)` (L128–L142)
Internal helper. Copies `source/**`, `symbols/**`, and `facts/**` subdirectories from a fixture snapshot into a temp directory, mirroring the mini-repo layout (`source/` → root, `symbols/` → `.osoji/symbols/`, `facts/` → `.osoji/facts/`). Expected.json answer keys are intentionally excluded.

### `build_claims_for_entries(entries)` (L145–L197)
Zero-LLM entry point. Imports `osoji.claim_builder.build_claims` and `osoji.evidence_builders.BuildContext` lazily. For each entry:
- Fixture entries (have `fixture_root`) get staged into a temp dir via `_stage_fixture_root`; path prefixes are stripped.
- Audit entries use live `REPO_ROOT`.
- Calls `build_claims([finding], ctx)` (L183).
Returns `(claims, meta)` where `meta` contains per-entry fill diagnostics: `gap_type`, `kinds`, `n_evidence`, `insufficient`, `evidence_fingerprint`.

### `build_summary(meta)` (L200–L222)
Aggregates build metadata into fill matrix + falsifiability metrics. Returns `escalation_rate` (fraction with `insufficient=True`) and `ce_gap_rate` (fraction with `gap_type == "uncategorized"`).

### `run_sdk_exploration(entries, *, model, max_turns, concurrency)` (L225–L368) — async
Explores via Claude Agent SDK. Imports `claude_agent_sdk` and osoji tool definitions lazily. For each entry, constructs an in-process MCP server with `read_file`, `grep`, `list_dir`, and `submit_triage_verdict` tools backed by `ExplorationExecutor`. Uses `asyncio.Semaphore(concurrency)` for parallel execution. Returns `(findings, traces_by_id, in_tokens, out_tokens)`.

Key behaviors:
- Fixture entries get their own `ExplorationExecutor` rooted at `<fixture_root>/source/` to prevent answer-key contamination (L272–L277).
- On missing verdict (no `submit_triage_verdict` call): sets `verdict="uncertain"`, `confidence=0.0` (L356–L361).
- Uses `type(message).__name__ == "ResultMessage"` duck-typed check (L337) to accumulate cost.

### `run(args)` (L371–L570) — async
Main orchestrator. Parses mode, optionally filters entries by `--only`, then dispatches:
- **build**: calls `build_claims_for_entries`, writes per-slug and summary JSON.
- **exploration-sdk**: calls `run_sdk_exploration`.
- **claim** (default): optionally runs `build_claims_for_entries` first (unless `--no-build`), then batches via `decide_chunk`.
- **exploration**: calls `entries_to_claims(strip_evidence=True)`, then batches.

Retry logic in `decide_chunk` (L433–L457):
- Up to 3 attempts per batch.
- On "too long" errors: bisects the chunk recursively (L441–L454).
- On transient failures: `asyncio.sleep(10 * (attempt + 1))` backoff.
- Second-pass retry for all failed batches after main loop completes (L475–L482).
- Undecided findings are surfaced as no-verdict entries, never silently dropped (L489).

Optional baseline comparison (L523–L548): loads a prior `explore-summary.json`, computes `baseline_disagreement_rate` and `baseline_disagreement_rate_nongray`. Ship gate: < 5% disagreement (spec 0001 criterion 5).

### `main()` (L573–L599)
Builds argparse with four subcommands (`explore`, `explore-sdk`, `claim`, `build`). All share the same argument set (L584–L597). Calls `asyncio.run(run(args))`.

---

## Manifest Schema

```json
{
  "commit": "<git sha>",
  "entries": [{
    "slug": "debris-dead-code-001",
    "origin": "audit" | "fixture",
    "category": "<native detector category>",
    "adjudicated_verdict": "confirmed" | "dismissed",
    "adjudication_notes": "...",
    "fixture_root": "<optional, e.g. tests/fixtures/bootstrap/cases/foo>",
    "gray": false,
    "finding": { "<Finding.to_dict() shape>" }
  }]
}
```

---

## Dependencies

- `osoji.config.Config` — configuration with `root_path`, `provider`, `model`
- `osoji.findings.Finding` — finding dataclass with `from_dict`, `to_dict`, `id`, `verdict`, `confidence`, `evidence`, `path`, `triage_reasoning`, `suggested_fix`, `severity`, `gap_type`, `evidence_fingerprint`
- `osoji.triage.Triage`, `Claim`, `TRIAGE_SYSTEM_PROMPT` — triage orchestration
- `osoji.claim_builder.build_claims` — mechanized evidence builder (lazy import)
- `osoji.evidence_builders.BuildContext` — context wrapping Config (lazy import)
- `osoji.triage_exec.ExplorationExecutor` — implements `read_file`/`grep`/`list_dir` tool semantics (lazy import)
- `osoji.llm.claude_code.ClaudeCodeProvider._neutral_cwd()` — static method for neutral CWD (lazy import)
- `osoji.tools` — tool definition dicts: `READ_FILE_TOOL`, `GREP_TOOL`, `LIST_DIR_TOOL`, `SUBMIT_TRIAGE_VERDICT_TOOL` (lazy import)
- `claude_agent_sdk` — `query`, `tool`, `create_sdk_mcp_server`, `ClaudeAgentOptions` (lazy import, optional)

---

## Output Artifacts

All written to `args.out` (default `tests/fixtures/bootstrap/traces/`):
- `{mode}-{slug}.json` — per-claim verdict + trace + adjudicated label
- `build-{slug}.json` — per-claim build result (build mode only)
- `{mode}-summary.json` — aggregate stats (accuracy, tokens, baseline disagreement)
- `build-summary.json` — fill matrix + escalation metrics (build mode only)

---

## Architectural Notes

- All imports of optional/heavy dependencies (`claim_builder`, `evidence_builders`, `triage_exec`, `claude_agent_sdk`, `claude_code`) are deferred with `# noqa: PLC0415` to avoid import failures when those modules aren't installed.
- `dataclasses.replace` is used pervasively to create modified Finding/Claim copies without mutation.
- The `ExitStack` in `build_claims_for_entries` manages temp directory lifetimes across all entries in a single pass, caching contexts by `fixture_root` to avoid redundant staging.
- `decide_chunk` is defined as a closure inside `run` to capture `triage`, `mode`, and retry config.