# A/B: decisions/0027 predicates + masking ladder + `description_debris` section

**PR B** (osojicode/work#81 + osoji#31, binding authority osojicode/wiki
decisions/0027). Rubric change measured by full-corpus replay on the 144-case
/ 91-non-gray corpus, judged against the PR #184 baseline pin.

## Design

- **Side A (baseline)**: run `eval-20260723-cd763451` — prompt sha
  `ed045852…` (pre-0027 rubric, 16 sections), the PR #184 pin run.
- **Side B (candidate)**: run `eval-20260723-ae5340c5` — prompt sha
  `807be646…` (predicates rewritten per 0027 ruling 1+3, masking ladder
  appended to significance per ruling 2, new `description_debris` section:
  17 sections). Same corpus, same model (claude-sonnet-4-6), same batch size
  (12), 1 repeat; claims rebuilt identically from frozen fixtures — the only
  variable is `system_prompt`.
- Both run NDJSONs are committed under `tests/fixtures/prompt_regression/runs/`.

## Variance control (read this before the table)

Same-prompt churn on this corpus is measured: `eval-20260723-ee9b529f` vs
`eval-20260723-cd763451` (both `ed045852…`) flip 13/96 shared cases (13.5%);
the older same-shape floor was 6/62 (9.7%). A/B flips: 19/144 (13.2%) — the
same order as the floor, so individual flips are attributed only by
mechanism, never by count (concepts/ablation-methodology).

## Headline (non-gray, n=91)

| metric | A (baseline) | B (candidate) | bound (PR #184 pin) |
|---|---|---|---|
| accuracy_nongray | 0.7143 (65/91) | **0.7692 (70/91)** | ≥ 0.64 PASS |
| tp_rate | 0.7805 (32/41) | **0.8537 (35/41)** | ≥ 0.68 PASS |
| fp_rate | 0.2400 (12/50) | **0.2000 (10/50)** | ≤ 0.33 PASS |
| undecided_rate | 0.0 | 0.0 | ≤ 0.05 PASS |
| description-family acc (n=37 ng) | 0.7027 | **0.7568** | — |
| non-family acc (n=54 ng) | 0.7222 | **0.7778** | — |

Net verdict movement: 7 fixed, 1 broke (case_208 dismissed→uncertain,
doc_incorrect_content, within-floor churn), 4 still-wrong flips, 7 gray
movements.

## Tripwires (decisions/0027 lists)

**Over-rotation sentinels** (hypotheticality dismissals — must not be
confirmed by an over-rotated rubric): no regressions; improvements only.
case_216/217/219 (gray latent_bug hypotheticals) moved confirmed→dismissed —
onto their adjudicated verdicts; case_201 moved uncertain→dismissed (now
correct); 233/200/225 stayed correct; 215/218 unchanged (gray, still
confirmed).

**Under-rotation fixtures** (the 7 panel overturns — the work#81
over-confirmation cluster): **cluster did not move.** case_228/242/243 still
confirmed, case_239 still uncertain, 240 still correct, 241/235 (gray)
unchanged.

## Adjudication of the unmoved cluster

Reasoning traces from side B (and from an iteration-2 probe, below) show the
misses are not rubric-text failures of the shipped section:

- **case_239** — evidence starvation, diagnosed from the trace: the model
  correctly observes the test's BigInt error message *supports* the comment's
  claim, but the evidence pack lacks `serializeAdapterCommand`'s
  implementation, so it lands 'uncertain'. Needs referenced-artifact
  resolution (osojicode/work#80), not prompt text.
- **case_242/243/228** — judgment-depth misses: conceding-then-pivoting
  (242), refuting the unqualified version of a qualifier-scoped claim (243),
  and constructing an implication beyond hedged wording (228). An iteration-2
  prompt adding qualifier-scoping, hedged-reading, and verdict-binding pivot
  language (run `eval-20260723-f60dfbee`, sha `eac41b06…`) moved **none** of
  them and drifted worse globally (accuracy 0.7253, non-family fp 0.3103,
  sentinel case_200 regressed to uncertain) — reverted; run committed as
  evidence. Two independent prompt formulations failing identically on cases
  the panel resolved with full-checkout context says the binding constraint
  is the evidence pack, not the rubric: routed to work#80.

## Recommendation

Accept side B (`807be646…`). It encodes ratified 0027 semantics, improves
every headline metric, moves the hypotheticality sentinels onto their
adjudicated verdicts, and costs one within-floor regression. The acceptance
target "≥3 of the 5 wrong under-rotation fixtures fixed" is missed (1 of 5:
case_201) and adjudicated above as evidence-bound — the plan's exit is "fix
the regression" in the evidence layer (work#80), with these four fixtures as
its acceptance set.

Baseline re-pinned from run `eval-20260723-ae5340c5` (point ∓1.5σ, rounded
outward): accuracy_nongray min 0.64→**0.70**, tp_rate min 0.68→**0.77**,
fp_rate max 0.33→**0.29**. All tightened; static CE/ME bounds untouched.

## Cost

Run ae5340c5: 357,553 in / 46,937 out (~$1.77). Iteration-2 probe f60dfbee:
429,902 in / 51,832 out (~$2.07). Total ~$3.84 of the $6 cap.

## Ruling addendum

_(pending JF review of PR B)_
