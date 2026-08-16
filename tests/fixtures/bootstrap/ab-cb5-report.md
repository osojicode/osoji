# cb-5 evidence-kind acceptance: callee_edges + cited_artifact (osojicode/work#95 + work#80)

Instrument-4 replay evidence for the cb-5 PR (stacked on the work#94 rubric
PR; all runs use the d8d7a74b rubric so the builder delta is isolated on top
of the new rubric). Runs: `runs/eval-20260816-cb5descfam.ndjson` (62 descfam
cases × 3 repeats) + two targeted flip checks (session scratch).

## Deterministic floor (no LLM, committed as a unit test)

`test_case_239_staged_bundle_carries_deciding_callee_edge`: the staged
case_239 bundle now carries `validateAdapterCommand → JSON.stringify @68`
with the call line's own source text
(`new Error(\`… ${JSON.stringify(details, null, 2)}\`)`) — via callee-seed
promotion, added when the first flip check showed the claim text never names
`validateAdapterCommand` (the model's one-frame-short blindspot reproduced in
the seed design). The case_239 fixture gained the previously-missing
`facts/src/utils/type-guards.ts.facts.json` sidecar (deterministic TS-plugin
extraction against the frozen snapshot; expected.json/finding.json
byte-identical — the fixture had under-snapshotted, replay staging never
regenerates facts).

## Acceptance targets

| case | expected | result | status |
|---|---|---|---|
| 172 vitest-setup flag | dismissed | targeted 2-case staging: **dismissed 3/3 @0.85**; descfam 12-claim batches: confirmed@info 3/3 | **met in isolation**; batch-sensitive residual (below) |
| 239 type-guards | dismissed | confirmed 3/3 (@0.85→0.9 as evidence grew) | **unmet** — adjudication-bound, consistent with ab-work94 |

- **172**: the `cited_artifact` mechanism works — in BOTH outcomes the
  reasoning explicitly uses the fetched L40 fact ("Deleted from process.env
  at module load (L40)"). The batch-mode confirm is a *different, finer*
  claim than the original FP: doc says the deletion happens in
  beforeAll/afterEach hooks, code does it at module level — confirmed at
  info. The original failure mode (artifact absent → model believes the flag
  doesn't exist) is gone. Whether hook-vs-module-level is drift or
  imprecision is an adjudication question; logged, not litigated. The
  2-case-vs-12-claim batch-composition sensitivity is itself a finding worth
  a resample-disagreement eye.
- **239**: with the deciding edge AND its source line in the pack, the model
  still reasons "validation throws its Error before JSON.stringify is
  reached" — not seeing that the Error's message construction evaluates
  `JSON.stringify(details)` first — and overrides the passing test's own
  `toThrow('Do not know how to serialize a BigInt')` assertion as "likely
  wrong". Salience is delivered; the inference gap is the model's
  (argument-evaluation order). Third consecutive instrument to leave this
  case standing (ab-descfam, ab-work92, ab-work94): the strongest evidence
  yet for the model-level hypothesis (work#88 upgrade A/B) over the
  evidence-bound one.

## Descfam regression (62 cases × 3 repeats, majority-of-3, nongray)

32 right / 7 wrong. Delta vs the work#94 run's new arm (same rubric, no
builders): **4 fixed** (124 uncertain→confirmed, 128 dismissed→confirmed,
166 + 167 →dismissed — the two accurate-comment guards now stably correct),
**2 broke** (172 above; 246 readme confirmed→dismissed 2-1, churn-range),
171 still-wrong (uncertain→dismissed). Repeat-0 slice metrics: tp 0.889,
fp 0.238, acc 0.795 — clean against every baseline bound (informational:
descfam-only slice; the corpus-wide gate re-validates at S3).

`description_class` emissions: 5/186, all confirmed@info on gray boundary
cases (202 ×3, 238 ×2) — pairing respected in every emission this run.

## Resample-disagreement measurement (feeds the work#97 baseline pin)

Within-run any-disagreement rate at repeats=3: **6/62 = 9.7%** — first
within-run measurement, below the 13.5% cross-run floor. Recommended pin in
the PR-1 follow-up: `resample_flip_rate: {"max": 0.15}` at repeats=3
(measured + margin; the metric is monotone in repeats, so the pin binds only
at the measured repeat count).

## Cost

Targeted flips 6 + 6 decisions, descfam 186 decisions ≈ 198 case-decisions
claim mode (+ the deterministic staging checks, free). Actuals: platform
dashboard (statusline silent-zero, work#90); pre-approved as spend event S2.
