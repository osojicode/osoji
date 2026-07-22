# Prompt regression corpus

This directory holds two different kinds of fixtures:

1. **Legacy bespoke case dirs** — `dead_code/case_00N_*`, `dead_params/case_00N_*`,
   `latent_bug/case_00N_*`, `plumbing/case_00N_*` (numbered below 101, no
   `case.json`). These back the statistical prompt-regression tests in
   `tests/test_prompt_regression.py` and are **not** corpus cases. Leave them
   alone — the discriminator for "is this a corpus case" is the presence of
   `case.json`, not the directory name.
2. **The adjudicated corpus** — `<category>/case_NNN_<slug>/` directories
   (numbered from `case_101` up) that carry a `case.json`. These are the V1-7
   evaluator's fixture corpus (osojicode/work#35): a growing set of real,
   human-adjudicated findings that prompt and pipeline changes get measured
   against, replayed by `corpus_replay.py` (osojicode/work#67), the proctor
   corpus-replay harness (osojicode/work#63), and the GEPA adapter
   (osojicode/work#68). This README documents the three formats those tools
   share; `scripts/eval_lib.py` is the library that reads and writes them, and
   is the enforcement point (schema tags are validated, not just documented).

Nothing in these formats may assume a Python target or the osoji repo
specifically — every path is POSIX and repo-relative, so a case swept from any
language, any project, replays the same way.

## `corpus-case/1` — one case directory

Path: `tests/fixtures/prompt_regression/<category>/case_NNN_<slug>/`, where
`<category>` is the native detector category (`dead_symbol`, `dead_parameter`,
`unactuated_config`, `obligation_implicit_contract`, `doc_stale_content`, ...)
and `NNN` numbers from `101` up, unique within the whole corpus (not per
category) so a case's directory name never collides across categories once
cases move around.

The category is the `:category` suffix of the finding's
`<producer>:<category>` detector string, with two wrinkles: `doc:` findings
carry unprefixed suffixes (`doc:stale_content`), so their category gains the
canonical `doc_` scorecard prefix (`doc_stale_content`); and `debris:`
findings keep the legacy debris vocabulary (`dead_code`, `latent_bug`,
`stale_comment`, ...) as-is, which is why debris-swept cases sit in
`dead_code/` alongside the dedicated detector's `dead_symbol/`.

A case directory contains:

- **`case.json`**

  ```json
  {
    "schema": "corpus-case/1",
    "slug": "<slug>",
    "category": "<category>",
    "detector": "<producer>",
    "gap_type": "reachability" | "description" | "contract" | "uncategorized",
    "language": "<language>",
    "origin": {
      "repo": "<owner/repo>",
      "remote": "<git remote URL>",
      "commit": "<sha the finding was swept at>",
      "swept_at": "<UTC ISO-8601 timestamp>",
      "osoji_version": "<osoji version that produced the sweep>",
      "sweep_run": "<identifier for the sweep run that proposed this case>"
    },
    "snapshot_ref": null | "<category>/<case_dir>",
    "evidence_policy": "rebuild" | "frozen"
  }
  ```

  `snapshot_ref` lets two cases share one `source/` snapshot (common when a
  sweep proposes several findings against the same repo state): when set, it
  is a POSIX path relative to the corpus root pointing at the case directory
  that actually holds `source/` (and its sidecars); this case's own directory
  then carries no `source/` of its own. `evidence_policy` controls how
  `build_case_claim` fills the claim's evidence at replay time — `"rebuild"`
  reruns the mechanized Claim Builder against the staged snapshot (evidence
  drifts with prompt/builder changes, matching production); `"frozen"` replays
  the evidence exactly as it was serialized at sweep time (isolates a prompt
  change from a builder change).

- **`finding.json`** — exactly `Finding.to_dict()` (`src/osoji/findings.py`):
  every triage-output field (`verdict`, `confidence`, `triage_reasoning`,
  `suggested_fix`, `severity`, `contract_class`) is `null` — a corpus case
  stores the *proposed* finding, never a stale verdict. `path` is
  snapshot-relative POSIX (relative to `source/`). Under `evidence_policy:
  "rebuild"`, `evidence` is `[]` (rebuilt at replay time); under `"frozen"`,
  `evidence` carries the serialized `Evidence` list from the original sweep.

- **`expected.json`** — the adjudicated answer key:

  ```json
  {
    "schema": "corpus-expected/1",
    "verdict": "confirmed" | "dismissed",
    "reasoning": "<adjudicator's reasoning>",
    "gray": false,
    "gray_reason": null | "<why this case is gray>",
    "expected_contract_class": null | "<contract_class for contract-gap cases>",
    "adjudicated_by": "<who decided this>",
    "adjudicated_at": "<UTC ISO-8601 timestamp>",
    "accepted": true | false
  }
  ```

  `gray` marks a case whose correct verdict is genuinely debatable — gray
  cases stay in the corpus (they're real data) but are excluded from the
  headline accuracy metrics (`tp_rate`, `fp_rate`, `accuracy_nongray`) so a
  hard, ambiguous case can't be gamed by a prompt that guesses its way to a
  score. `accepted` gates whether `load_corpus` will ever load the case at
  all — see the acceptance flow below.

- **`source/`** — the snapshot files a detector would have scanned, laid out
  as a mini-repo (or, when `snapshot_ref` is set, this key lives on the
  referenced case instead).
- **`symbols/`, `facts/`, `shadow/`** (all optional) — the corresponding
  `.osoji/symbols/`, `.osoji/facts/`, `.osoji/shadow/` sidecars, mirrored
  under the case directory the same way `source/` mirrors the repo root.
  `stage_case` copies whichever of these exist into a staged mini-repo.

### Acceptance flow (`_holding/` -> a numbered case dir)

Sweeps propose candidate cases into `_holding/` with a sweep-proposed verdict
and `accepted: false` — `load_corpus` skips everything under `_holding/`
unconditionally (with a warning for unaccepted cases anywhere else), so
holding entries are inert until reviewed:

1. A sweep run emits a candidate case directory under `_holding/` (`case.json`
   + `finding.json` + `expected.json` with `accepted: false` and the sweep's
   proposed verdict/reasoning + `source/` and sidecars).
2. A human reviews it: does it replay cleanly? Is the proposed verdict right?
   Should it be marked `gray`?
3. On acceptance, the reviewer sets `expected.json`'s `accepted: true` (and
   corrects `verdict`/`reasoning`/`gray`/`gray_reason` if the sweep's proposal
   was wrong).
4. `git mv` the directory from `_holding/<name>` to
   `<category>/case_NNN_<slug>` — `NNN` is the next free number `>= 101`
   across the *whole* corpus, not per category.
5. Add the new case's key to `splits.json` (see below).
6. Commit.

## `corpus-splits/1` — `splits.json`

```json
{
  "schema": "corpus-splits/1",
  "seed": 12345,
  "ratios": {"train": 0.5, "val": 0.25, "holdout": 0.25},
  "assignments": {"<case key>": "train" | "val" | "holdout"}
}
```

`suggest_split(case_key, seed, ratios)` is the deterministic default
(`sha256(f"{seed}:{case_key}")`, bucketed by `ratios`); a human may override
it for balance when accepting a case. Assignments are **append-only** — once a
case is assigned a split it never moves, so nothing that has ever been
`holdout` can leak into `train` later. This PR does not ship a real
`splits.json`; it lands empty in the next PR once cases exist to assign.

## `osoji-verdict/1` — run output NDJSON

A replay run's output is one JSON object per line (UTF-8, bare `\n` line
endings, no BOM): a **verdict record** per decided claim, followed by exactly
one **`run_meta` trailer as the last line**. `write_verdict_ndjson` enforces
the trailer-last ordering; `read_verdict_ndjson` rejects a stream whose last
line isn't a valid trailer.

### Verdict record

| Field | Meaning |
| --- | --- |
| `schema` | `"osoji-verdict/1"` |
| `record` | `"verdict"` |
| `run_id` | Identifier for the run this record belongs to |
| `variant` | Which prompt/pipeline variant produced this verdict |
| `repeat` | 0-based repeat index (for repeated trials of the same case/variant) |
| `source` | `"corpus"` or `"bootstrap"` |
| `case` | The case key (`"<category>/<case_dir>"`) |
| `finding_id` | The finding's stable `id` |
| `detector`, `category`, `gap_type` | Copied from the finding |
| `path`, `symbol`, `line_start`, `line_end` | Copied from the finding |
| `expected_verdict`, `gray` | Copied from `expected.json` |
| `verdict` | `"confirmed"` \| `"dismissed"` \| `"uncertain"` \| `null` (`null` = undecided: chunk failure or an insufficient-evidence pass-through) |
| `confidence`, `severity`, `contract_class`, `triage_reasoning`, `suggested_fix` | Triage output fields |
| `insufficient_evidence` | Whether the Claim Builder flagged the claim as insufficiently evidenced |
| `evidence_policy` | `"rebuild"` \| `"frozen"`, copied from the case |
| `correct` | `bool` \| `null` — `null` when `verdict` is `null` |

### `run_meta` trailer (last line)

| Field | Meaning |
| --- | --- |
| `schema` | `"osoji-verdict/1"` |
| `record` | `"run_meta"` |
| `run_id` | Matches every verdict record's `run_id` |
| `started_at`, `finished_at` | UTC ISO-8601 |
| `duration_s` | Wall-clock run duration |
| `variants` | `{name: {prompt_sha256, prompt_source}}` for every variant in the run |
| `provider`, `model` | The LLM provider/model used |
| `osoji_commit` | Git commit of osoji at run time |
| `claim_builder_schema_version` | `claim_builder.CLAIM_BUILDER_SCHEMA_VERSION` at run time |
| `corpus` | `{root, n_cases, n_gray, split, only, exclude_gray}` — how `load_corpus` was called |
| `repeats`, `repeat_offset` | Repeat-trial configuration |
| `batch_size` | Claims per Triage call |
| `tokens` | `{input, output}` |
| `metrics` | The `compute_metrics(...)` output for this run |

### Convention: commit evaluated runs

A run that was actually used to make a decision commits its NDJSON to
`tests/fixtures/prompt_regression/runs/<run_id>.ndjson`. Committed evidence is
the default; leaving a run's output only in a scratchpad is the anti-pattern —
nobody else can audit or replay a decision that isn't in the tree.

## Running a replay

`scripts/corpus_replay.py` is the CLI over `eval_lib.py`'s orchestration
(`evaluate_corpus`): it stages cases, builds claims, decides them through
Triage under one or more prompt variants, and writes `osoji-verdict/1`
NDJSON. It spends real LLM tokens — `--gate-check` is the only mode that
doesn't (no provider is constructed, no API key is needed).

```bash
# Is the corpus big enough and split-covered for a GEPA run yet?
python scripts/corpus_replay.py --gate-check

# Replay the whole corpus under the default rubric, 1 repeat, to stdout.
python scripts/corpus_replay.py

# Compare the default rubric against one with a section omitted, 3 repeats
# each, restricted to the train split, output committed to the tree.
python scripts/corpus_replay.py \
  --variant baseline=@default \
  --variant no_significance=@omit:significance \
  --repeats 3 --split train \
  --out tests/fixtures/prompt_regression/runs/eval-001.ndjson
```

Key flags: `--corpus`/`--bootstrap`/`--source {corpus,bootstrap,both}` select
which cases to replay (bootstrap cases replay against the live repo tree, not
a snapshot — see `eval_lib.cases_from_bootstrap_manifest`); `--variant
name=value` is repeatable (`@default`, `@omit:section1,section2`, or a file
path — see `eval_lib.resolve_variant`); `--split`/`--only`/`--exclude-gray`
filter the corpus source; `--provider`/`--model` pick the LLM; `--out -`
(the default) writes NDJSON to stdout, otherwise to the given path. Run
`python scripts/corpus_replay.py --help` for the full list.
