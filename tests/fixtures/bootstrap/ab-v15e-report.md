# V1-5e gate — debris rubric A/B (work#52)

**Date:** 2026-07-05 · **Branch:** `v1-5e-debris-rubric-flip` · **Status: awaiting JF adjudication**

## What was measured

Phase 3 debris was the last Triage path on the preserved legacy
`DEBRIS_TRIAGE_SYSTEM_PROMPT` (decision 0014: the V1-3 cutover was
re-plumbing, not re-rubric; the flip is a measured change). This A/B replays
the live `.osoji/findings/` debris corpus through the unified Triage stage
twice — **identical claims, identical evidence bundles, identical code; the
only variable is `system_prompt`**:

- **Side A** — `DEBRIS_TRIAGE_SYSTEM_PROMPT` (legacy, production until this PR)
- **Side B** — `TRIAGE_SYSTEM_PROMPT` (unified tri-section rubric)

Corpus: 68 raw debris findings (2026-07-01 osoji-on-osoji audit sidecars),
62 eligible claims, 0 would-escalate. Provider `anthropic`, medium tier
(`claude-sonnet-4-6`) — same as the v15a–d gates. Claims built by
`build_debris_claims` with the impl-hash staleness gate bypassed exactly as in
`measure_debris_cutover.py` (this branch changes source; both sides see
identical inputs). Harness: `scripts/ab_v15e_debris_rubric.py`.

## Run 1 addendum — single-batch cross-wiring (led to work#57)

The first run mirrored production's exact call shape: **all 62 claims in one
`decide_batch` call**. Side A came back aligned; **side B's verdicts went
off-by-one from ~batch_index 5 onward** — each verdict's reasoning describes
the *next* claim's content, and the final verdict's reasoning narrates the
confusion outright ("batch_index 61 doesn't exist… submitting as dismissed to
satisfy the validator"). Side B also burned 2× input tokens (767K vs 377K),
consistent with one completeness-validator retry that came back still
misaligned.

The V1-5a cross-wiring defence (symbol echo + completeness validator) could
not catch this because **debris claims carry `symbol=None`** — the echo check
has nothing to compare. Filed as **work#57** (route Phase 3 through
`decide_junk_claims` chunking and/or add a `path:line` fallback echo).
Run 1's side-B verdict deltas are therefore **structurally invalid as rubric
measurement** and are not adjudicated here; the raw JSON is preserved in the
session scratchpad.

## Run 2 — chunked (valid measurement)

Run 2 routes both sides through production `decide_junk_claims`
(BATCH_SIZE=12, same-file adjacency, bisect-on-failure) — chunk shape
identical on both sides, so the prompt stays the single variable. Note this
is the call shape work#57 proposes for production Phase 3.

**Results (run 2):**

| | A (legacy) | B (unified) |
|---|---|---|
| confirmed | 33 | 28 |
| dismissed | 23 | 32 |
| uncertain | 6 | 2 |
| undecided | 0 | 0 |
| tokens | 598,682^ / 23,714v | 682,975^ / 33,678v |

**Changed verdicts: 13/62.** Alignment verified (every changed verdict's
reasoning references its own claim — no run-1-style cross-wiring).

### Variance control (read this before the table)

Per decision 0016 (decision 4), a same-prompt control bounds attribution:
side A run-1 (single-batch) vs side A run-2 (chunked) — **same legacy prompt —
differ on 16/62 verdicts**. Two variables separate those runs (batch shape and
sampling), so 16 is an upper bound on same-shape churn, but the conclusion
stands: **within-prompt churn is the same order as the 13/62 cross-prompt
delta, so individual verdict changes cannot be attributed to the rubric.**
What is attributable is the aggregate, which is directionally stable across
both runs: the unified rubric dismisses more (Significance predicate active),
is more decisive (uncertain 6 → 2), and still confirms sharp findings the
legacy prompt missed (item 9 below).

## Adjudication table

Each row: what changed, the mechanism behind the disagreement (theory of harm
+ concrete trigger site), and a recommendation. Verdict labels are noisy
per the variance control — the *mechanism classes* are the adjudicable units.

| # | Site | A → B | Mechanism | Read |
|---|---|---|---|---|
| 1 | `audit.py:1894` dead_code | confirmed → uncertain | The surrounding-code window (L1884-1905) does not contain the flagged L1874 filter / L1895 guard. A confirmed from the claim's self-consistency; B refused to decide without seeing the lines. | **B better calibrated** — evidence-window honesty. |
| 2 | `claim_builder.py:25` dead_code | confirmed → dismissed | Claim is stale against today's tree: `Path` no longer appears in claim_builder.py at all (sidecars predate the V1-4/5 rewrites; staleness gate deliberately bypassed for measurement). Judged per-bundle: A's absence-read was cleaner; B hedged on "may be used in annotations". | **A slightly better per-bundle; moot on the current tree.** |
| 3 | `tokens.py:58` latent_bug | confirmed → dismissed | Tool-token undercount is shadow-doc-documented intentional behavior; the reservation path tolerates undercounting (retry logic backstops). B dismisses on Significance. | **Philosophy class S** (see below). |
| 4 | `tokens.py:102` latent_bug | confirmed → dismissed | 10K-entry cache cap silently stops caching: bounded-memory design, correctness unaffected. B: performance nuance, not a gap. | **Philosophy class S.** |
| 5 | `registry.py:52` dead_code | uncertain → **confirmed (FALSE POSITIVE)** | Ground truth: `_discover_entry_point_plugins()` IS called at `plugins/__init__.py:43`. The evidence bundle said "zero calls" because needle extraction dropped the backticked ``name()`` form and swept junk needles instead (filed as **work#58**). Given that (wrong) evidence-of-absence, B's confirm follows the ratified evidence-of-absence semantics; A's uncertain was luckier, not sounder. | **Upstream evidence bug, not a rubric defect.** The one B-confirmed FP in the set. |
| 6 | `push.py:310` latent_bug | confirmed → dismissed | The 200=duplicate / 201=new convention is the documented osoji-teams ingest contract (shadow-doc-backed). A confirmed *despite* citing the documentation. | **B better** — documented contract ≠ latent bug. |
| 7 | `paths.py:157` dead_code | confirmed → dismissed | self_test filter brittleness is future-hypothetical; current filters cover all current descriptions and tests pass. B: reality-now framing. | **Philosophy class S.** |
| 8 | `scorecard.py:249` latent_bug | uncertain → dismissed | B reasons from pipeline structure: junk analyzers operate on the same shadow-inventory population, so the numerator/denominator mismatch path doesn't exist; plus the >0 guard. | **B better** — structural argument beats hedging. |
| 9 | `test_audit_debris_cutover.py:100` stale_comment | dismissed → **confirmed** | The comment conflates two ineligibility mechanisms: `stale_comment` is flag-ineligible (`cross_file_verification_needed`), `misleading_docstring` is category-ineligible. Verified against `_is_eligible` in claim_builder.py. A developer could wrongly believe the flag would make `misleading_docstring` eligible. | **B better — a genuine TP the legacy rubric dismissed.** The flip is not just dismissal-bias. |
| 10 | `test_plugin_integration.py:20` latent_bug | confirmed → dismissed | Fixture uses schema-nonconformant `usage`/`kind` values, but the test never schema-validates; harm ("agents learn wrong shapes") is speculative. | **Philosophy class S.** |
| 11–13 | `test_prompt_regression.py:441/461/481` latent_bug | uncertain → dismissed ×3 | 8-value unpacks match the current return arity; the claim is future-fragility ("if the arity changes"), not a current gap. | **Philosophy class S** — consistent triple. |

### The one substantive pattern (class S): significance/reality-now dismissals

Nine of thirteen changes are the same mechanism: the legacy prompt's bias is
"if ambiguous, CONFIRM" with no significance test, so it surfaces
*known-limitation nudges* (documented trade-offs, future-fragility notes,
fixture hygiene). The unified rubric requires all three TP predicates —
reality **now**, significance, actionability — and dismisses these. That is
the rubric working as the spec defines a true positive, and it is the same
standard the other seven detectors have shipped under since the V1-5 wave.

**Open question for JF** (rubric evolution, not a flip blocker): should
debris findings that fail only Significance be *demoted* (severity=info,
kept) rather than dismissed? Signal conservation favors demotion; the current
unified rubric — everywhere, not just debris — dismisses. If demotion is
wanted it should be a rubric change measured across all detectors, not a
debris carve-out.

## Recommendation (pending JF ruling)

Ship the flip. Supporting reads:

1. **Aggregate direction is the spec's TP definition working**, and it is the
   standard every other detector already ships under — debris was the last
   holdout, running a rubric with no significance predicate and a
   confirm-on-ambiguity bias.
2. Where B and A disagree on *evidence reading* (not philosophy), B was
   better three times (items 1, 6, 8, plus the sharper TP at item 9) and
   worse twice — once marginal-and-moot (2), once caused by an upstream
   needle-extraction bug (5 → work#58), not the rubric.
3. Per the variance control, keeping the legacy prompt buys no stability:
   same-prompt churn (16/62 across shapes) is as large as the rubric delta.
4. Unifying removes the last dual-rubric maintenance surface (one prompt to
   optimize, per the spec's "single largest optimization target").

Adjudication asked of JF: ratify or veto the class-S pattern (9 items above)
and the two B-worse reads; the flip PR stays draft until then.

## Byproducts of this gate

- **work#57** — Phase 3 debris single-batch `decide_batch` + `symbol=None`
  claims defeat the cross-wiring guard (run-1 off-by-one evidence).
- **work#58** — Claim Builder needle extraction drops backticked `name()`
  call forms; junk needles produce false evidence-of-absence (item 5).

## Cost

Anthropic API (not Max quota): run 1 ≈ 1.14M in / 32K out; run 2 ≈ 1.28M in /
57K out. Both raw JSONs preserved in the session scratchpad.
