# scripts\eval_lib.py
@source-hash: edc6b22e17f41e3c
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:51Z

## Purpose
Evaluator library for the V1-7 corpus regression harness. Handles on-disk corpus-case loading, snapshot staging, claim construction, deterministic metrics computation, and LLM-orchestration (`evaluate_corpus`) that decides claims through unified Triage. Consumed by `corpus_replay.py`, the proctor harness, and the GEPA adapter.

## Module-Level Constants (L38–55)
- `REPO_ROOT` (L38): Absolute path to repo root, derived from `__file__`. Also inserts `src/` into `sys.path` (L39).
- `CORPUS_ROOT` (L50): Default corpus fixture path: `REPO_ROOT/tests/fixtures/prompt_regression`.
- Schema version strings used for validation throughout:
  - `CORPUS_CASE_SCHEMA = "corpus-case/1"` (L52)
  - `CORPUS_EXPECTED_SCHEMA = "corpus-expected/1"` (L53)
  - `CORPUS_SPLITS_SCHEMA = "corpus-splits/1"` (L54)
  - `VERDICT_SCHEMA = "osoji-verdict/1"` (L55)

## Key Data Classes

### `CorpusCase` (L58–72) — frozen dataclass
Represents one adjudicated corpus-case/1 entry ready for staging and replay.
- `key`: `"<category>/<case_dirname>"` POSIX path
- `finding`: `Finding` object (triage-output fields are None)
- `expected_verdict`: `"confirmed"` | `"dismissed"`
- `evidence_policy`: `"rebuild"` | `"frozen"`
- `snapshot_root`: resolved snapshot directory (case_dir or snapshot_ref target)
- `source`: `"corpus"` | `"bootstrap"` (default `"corpus"`)

### `Variant` (L255–267) — frozen dataclass
Named system-prompt variant for replay runs.
- `name`, `system_prompt`, `prompt_source` (`"@default"` | `"@omit:..."` | file path)
- `prompt_sha256` property (L264–267): SHA-256 hex of `system_prompt` for run_meta identity.

### `GateReport` (L675–687) — dataclass
Result of GEPA pilot gate check: counts, coverage booleans, missing/extra keys, overall `passed`.

### `EvalRun` (L726–731) — dataclass
Completed replay result: `records: list[dict]` (verdict records) + `run_meta: dict` (trailer).

## Core Functions

### `load_corpus` (L86–179)
Loads accepted `corpus-case/1` entries from disk.
- Globs `*/case_*/case.json`, skips `_holding/` directories.
- Validates `case.json` and `expected.json` schema tags; raises `ValueError` on mismatch.
- Skips unaccepted cases (warns), gray cases (if `exclude_gray`), split-filtered cases.
- Resolves `snapshot_ref` via `_resolve_posix_ref` for cross-case snapshot sharing.
- Returns `list[CorpusCase]`.

### `stage_case` (L195–227)
Materializes a case's snapshot as a mini-repo under `workdir`.
- Sanitizes key (`/` → `__`) for directory name.
- Copies `snapshot_root/source/**` to target; copies `symbols/`, `facts/`, `shadow/` to `.osoji/` counterparts.
- Raises `ValueError` for `"rebuild"` policy with missing `source/` directory.
- Returns `Config(root_path=target, respect_gitignore=False)`.

### `build_case_claim` (L230–247)
Builds a `Claim` per evidence policy:
- `"rebuild"`: calls `build_junk_claims([case.finding], BuildContext(config))[0]`
- `"frozen"`: wraps finding as `Claim(finding=case.finding)` unchanged
- Unknown policy raises `ValueError`.

### `resolve_variant` (L270–305)
Parses `name=value` `--variant` spec into a `Variant`:
- `@default` → `TRIAGE_SYSTEM_PROMPT`
- `@omit:s1,s2` → `render_triage_prompt(omit=[s1, s2])`
- Otherwise: reads value as UTF-8 file path.

### `cases_from_bootstrap_manifest` (L313–349)
Wraps bootstrap manifest entries as `CorpusCase` objects with `source="bootstrap"`, `evidence_policy="rebuild"`, `snapshot_root=REPO_ROOT`. Dynamically imports `triage_bootstrap.load_manifest` at runtime.

### `compute_metrics` (L433–536)
Computes flat metrics dict from verdict records + cases:
- `tp_rate`, `fp_rate` (non-gray only), `tp_rate_by_detector`, `fp_rate_by_detector`
- `accuracy_nongray`: fraction of decided non-gray records with correct verdict
- `ce_gap_gap_type`: fraction of cases with `gap_type == "uncategorized"` (static)
- `ce_gap_contract_other`: fraction of decided contract records with `contract_class == "other"`
- `me_overlap`: union-find cross-producer overlap fraction (static, via `_me_overlap`)
- `escalation_rate`: fraction of rebuild records with `insufficient_evidence`
- `uncertain_rate`, `undecided_rate`, `gray_count`, `n_cases`, `n_cases_by_category`

### `check_thresholds` (L539–574)
Compares metrics dict against a baseline with `{"min": ..., "max": ...}` bounds per metric name. Skips missing metrics and non-scalar values. Returns list of violation strings (empty = passed).

### `write_verdict_ndjson` / `read_verdict_ndjson` (L582–629)
NDJSON I/O for `osoji-verdict/1` format. Write appends `run_meta` as last line. Read validates schema/record tags on every line, returns `(records, run_meta)`.

### `load_splits` (L637–646)
Loads and validates `corpus-splits/1` JSON file.

### `suggest_split` (L649–667)
Deterministically buckets a `case_key` into a split by SHA-256 hash; `sha256(f"{seed}:{case_key}")[:16]` → fraction → cumulative ratio partition.

### `check_gepa_gate` (L689–718)
Validates GEPA pilot readiness: `nongray_count >= required`, assignments non-empty, exact coverage (no missing or extra keys). Returns `GateReport`.

### `evaluate_corpus` (L821–979) — async
Main LLM orchestration entrypoint:
1. Validates non-empty cases/variants.
2. Builds runtime `Config` via `config_factory` or default.
3. Stages all cases and builds claims via `_stage_and_build_claims` (BEFORE opening provider).
4. Creates or reuses provider; owns-provider = closes on finish.
5. For each `(variant, repeat)` pair: calls `decide_junk_claims` with that variant's system prompt; accumulates token counts and verdict records.
6. Builds `run_meta` trailer with timing, token totals, and embedded `compute_metrics`.
7. Returns `EvalRun`.

### `select_cases` (L982–1022)
CLI-style case selection across corpus/bootstrap/both sources. Applies `only`/`exclude_gray` to all; `split`/`splits` only to corpus source.

## Internal Helpers
- `_resolve_posix_ref` (L75–83): POSIX-safe path joining (splits on `/` not OS separator).
- `_copy_tree` (L182–192): Recursive file copy mirroring structure.
- `_producer` (L357–360): Extracts producer half from `"<producer>:<category>"` detector string.
- `_ranges_overlap` (L363–368): Checks whether two line ranges overlap (returns False if any bound is None).
- `_me_overlap` (L371–422): Union-find algorithm grouping findings by path+symbol/line overlap across different producers; returns fraction in overlapping groups.
- `_rate` (L425–430): Generic rate computation over filtered record lists.
- `_git_commit` (L741–754): Best-effort `git rev-parse HEAD`; returns `"unknown"` on failure.
- `_stage_and_build_claims` (L757–781): Per-case staging (corpus: isolated snapshot; bootstrap: shared live-repo config) + claim building.
- `_build_verdict_record` (L784–818): Constructs one `osoji-verdict/1` verdict dict from case+claim+finding.
- `default_run_id` (L734–738): Generates `eval-YYYYMMDD-<8hex>` run ID.

## Key Architectural Decisions
- **Staging before provider construction** (L907): prevents resource leaks on staging failures.
- **Claims built once per case**, independent of variant/repeat — only the decide pass varies.
- **`bootstrap` cases share one `Config(root_path=REPO_ROOT)`** rather than staged snapshots.
- **Production-shaped batching** via `decide_junk_claims` with `JUNK_BATCH_SIZE` chunking.
- **Injected provider** (test) is never closed; owned provider is closed via `try/finally`.
- `_me_overlap` uses union-find with path compression for multi-producer overlap detection.
- `suggest_split` is deterministic but overridable by humans for balance.
