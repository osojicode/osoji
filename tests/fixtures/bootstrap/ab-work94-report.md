# Rubric A/B: decisions/0029 encoding — verification domains + ambiguous-description class (osojicode/work#94)

Instrument-3 prompt A/B gating the work#94 PR (decisions/0022: sha bump + A/B
evidence in one PR). Arms: `old` = the pre-change production rubric
(sha `807be646…`, extracted byte-identical from main), `new` = this PR's
rubric (sha `d8d7a74b…`: `verification_domains` section, ambiguity bullet in
`description_debris`, declared-scope clause, checkout qualifiers on the two
honest-zero clauses, `description_class` tool field).

## Design

- Full corpus, 151 cases, 1 repeat per arm, claim mode, anthropic default
  model. Run: `runs/eval-20260816-work94.ndjson` (`eval-20260816-work94`).
- Iteration smokes (5-case acceptance set, 3 repeats) preceded the full run;
  two strengthenings came out of them, both principle-shaped: (1) "routing is
  binding" + defensive-breadth + mirror-error + derived-artifacts-cannot-move-
  world-facts sentences in `verification_domains` — added after the new arm
  escaped the section by reframing a (b)-domain doubt as a checkout-internal
  design contradiction (case_243) and by adjudicating a platform-attributed
  behavior internally (case_242); (2) the declared-scope clause in
  `description_debris`.
- Context for scoring: the corpus expectations for 228 (dismissed→confirmed
  ambiguous/info) and 243/242 (re-grounded reasoning) changed IN THIS PR per
  the JF rulings, so the old arm is scored against the new answer key — an
  old-arm miss on 228 is the demanded delta, not a regression.

## Headline metrics (nongray, vs evaluate-baseline.json bounds)

| arm | tp_rate | fp_rate | accuracy | uncertain | undecided | gate |
|---|---|---|---|---|---|---|
| old | 0.826 | 0.216 | 0.773 | 0.026 | 0.000 | holds |
| new | 0.804 | 0.216 | 0.763 | 0.053 | 0.000 | **holds** |

Bounds: tp ≥ 0.77, fp ≤ 0.29, accuracy ≥ 0.70, undecided ≤ 0.05, ce_gaps —
no violation on either arm; `evaluate-baseline.json` ships untouched.
The tp/accuracy deltas (−2.2 / −1.0 pt ≈ 1–2 cases) sit inside the measured
13.5% same-prompt churn floor (ab-descfam-report.md); the uncertain-rate rise
(+2.7 pt) is partly the design working — 0029 routes unadjudicable claims to
uncertain (e.g. 124/171 moved dismissed→uncertain on expected-confirmed doc
cases: signal parked for review, not destroyed).

## Acceptance set (expected → old → new; smokes at 3 repeats in parentheses)

| case | expected | old | new | status |
|---|---|---|---|---|
| 228 agent-demo | confirmed@info+ambiguous | confirmed@info | confirmed@info (3/3 info) | **verdict+severity met**; class not self-emitted |
| 242 cleanup-procs | dismissed | confirmed@info | confirmed@info (3/3) | unmet as dismissal — but lands exactly the ticket's sanctioned alternative ("ambiguous/info for the parenthetical") minus the class label |
| 243 jdi-bridge | dismissed | confirmed@info | confirmed (2 info/1 warn) | **unmet** — survived three text iterations; see below |
| 239 type-guards | dismissed | dismissed | unstable: dismissed/uncertain/confirmed-ambiguous across samples | no stable wrong-confirm; owned by work#95 callee edges |
| 167 line-ref | dismissed | uncertain | uncertain (smokes: 2-3/3 dismissed) | no wrong confirm; churns dismissed↔uncertain |

## Verdict flips (old→new, full run): 20/151 (13.2%)

Non-gray: 3 fixed (121 dead_symbol uncertain→dismissed, 207 rust-doc
confirmed→dismissed, 139 obligation dismissed→confirmed), 4 broke (128
doc_stale confirmed→dismissed, 248 npx-test confirmed→dismissed, 166
arch-comment dismissed→uncertain, 239 dismissed→confirmed-ambiguous@info in
this sample), 2 signal-parking moves (124, 171 dismissed→uncertain on
expected-confirmed). Remainder gray. Net non-gray damage ≈ churn-floor noise;
no systematic direction.

## description_class mechanism

Live: 4 emissions, all in the new arm — 236 (gray boundary stub)
confirmed-ambiguous@info; 202 (gray) confirmed-ambiguous@info; 239
confirmed-ambiguous@info (its unstable sample); 147 confirmed-ambiguous at
**warning** — the model violated the info pairing once (the schema field
description states the pairing; nothing clamps it, per the no-severity-clamp
decision). The class is never self-emitted on 228 — the model that commits to
one reading does not recognize its reading as one of two; self-diagnosed
ambiguity emission appears structurally rare. The complementary mechanical
path is work#97's resample-disagreement (239's dismissed/uncertain/
confirmed-ambiguous scatter is exactly that signal).

## Decision inputs

1. **Gate holds; PR merges on this evidence.** Baseline untouched.
2. **243 is the residual specimen of the adjudication-bound cluster**: it has
   now survived two descfam rubric formulations (ab-descfam), full agentic
   evidence (ab-work92), and three 0029 text iterations including sentences
   aimed at its exact escape ("Nevertheless…" reframing; shadow-doc-as-world-
   authority; declared-scope). Per the strategy reset, it stays logged in the
   corpus as an expected-dismissed miss rather than litigated further.
   Remaining hypotheses: model-level adjudication gap (candidate for a model
   upgrade A/B, work#88) or expected-verdict re-examination.
3. **242**: the model stably lands the ticket's sanctioned alternative
   (confirm-as-info on the parenthetical). If JF prefers, re-adjudicating
   expected.json to confirmed@info+ambiguous makes 242 a scored hit; kept
   dismissed in this PR (panel's checkout-exhibited grounds still stand).
4. **147's warning-severity ambiguous emission** suggests watching the
   pairing violation rate once emissions accumulate; a `ce_gap`-style budget
   is premature at n=1.

## Cost

Full run 302 case-decisions + three iteration smokes (10 + 15 + 15) ≈ 342
decisions, claim mode. Actuals: platform dashboard (spend statusline is
silent-zero broken, work#90); pre-approved as spend event S1 this session.
