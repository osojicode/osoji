# work#59 A/B report: Significance as grade (demote-not-drop) vs three-predicate gate

**Ticket:** osojicode/work#59 · **Branch:** `work59-significance-grade-not-gate` · **Date:** 2026-07-07

## Design

Same-claims prompt A/B per decision 0016 (the v15e instrument, harness
`scripts/ab_v159_significance_grade.py`): identical claims built once from the
live `.osoji/findings/` debris corpus (68 raw → 62 eligible, 0 would-escalate),
decided in identical production chunks (`decide_junk_claims`, BATCH_SIZE=12);
the ONLY variable is `system_prompt`:

- **side A**: frozen pre-ruling rubric (TP = Reality + Significance +
  Actionability; dismiss on any failure) — the prompt shipped by V1-5e.
- **side B**: ruled rubric (TP = Reality + Actionability; Significance grades
  severity, real-but-minor → info; Reality is explicitly reality-NOW).

Provider: anthropic, tier medium, on both sides and the control.

## Variance control (read this before the table)

Same-prompt control (side A twice, same chunking): **6/62 verdicts changed,
confirmed-count wobble 34 vs 30, info-count wobble 15 vs 9.** Individual
verdict flips and small count deltas are sampling noise; only mechanism
classes and directional aggregates are adjudicable.

## Headline

| | A (three-predicate) | B (grade-not-gate) |
|---|---|---|
| confirmed | 30 (11 info / 18 warning / 1 error) | 31 (12 info / 19 warning) |
| dismissed | 26 | 29 |
| uncertain | **6** | **2** |
| changed vs A | — | 7/62 (control floor: 6/62) |
| **dismissed → confirmed@info (the ruling's target class)** | — | **2** |
| tokens | 547K^ / 28.5K v | 510K^ / 24.6K v |

No mass demotion (info count stable within control wobble), no confirm-side
collapse, slightly cheaper. The attributable effects are the two target-class
conversions (both with on-mechanism reasoning) and the uncertain → decisive
shift (6 → 2, all via explicit reality-now reasoning).

## Adjudication table

| # | Site | A → B | Mechanism | Read |
|---|---|---|---|---|
| 1 | `llm/tokens.py:102` latent_bug | dismissed → **confirmed@info** | THE ruled exemplar (v15e class-S item 4). A: "deliberate bounded-cache design" — the intent-flavored dismissal. B: cache silently stops caching at 10K entries, no eviction, no warning — real, actionable, minor → info. | **The ruling working as specified.** For JF: does the bounded-cache *documented intent* make this a Reality dismissal instead (per the 0018/addendum vocabulary), or is silent cache-stop beyond the documented bound a real gap? This is the demote-vs-Reality boundary in the flesh. |
| 2 | `tests/test_prompt_regression.py:457` dead_code | dismissed → **confirmed@info** | A: the two trial functions serve different fixtures. B: bodies are identical → near-duplicate helper, real-but-minor hygiene → info. | Target-class conversion; arguably brushes decisions/0018 (style vs content). JF adjudicates. |
| 3–5 | `tests/test_prompt_regression.py:441/461/481` latent_bug ×3 | uncertain → dismissed ×3 | A hedged (production signature not in evidence). B dismisses decisively: "future-fragility claim, not a current defect; the unpack is either correct now (CI passes) or broken now." | **Reality-NOW language converting hedges into clean dismissals** — the preserved status-quo boundary behaving more decisively. Relevant to the UNRULED boundary (below). |
| 6 | `claim_builder.py:25` dead_code | uncertain → dismissed | Stale-against-tree claim; the control also churned on it. | Noise class. |
| 7 | `scorecard.py:249` latent_bug | confirmed → dismissed | Flip-flops in every run pair including the control (structural-argument item, v15e item 8). | Noise class. |

## The unruled boundary, observed

JF has NOT ruled whether not-yet-real robustness notes should *surface* at
info instead of dismissing. Side B (as written) dismisses them on
Reality-now, decisively — rows 3–5. If JF later rules they should surface,
that is a one-line rubric change ("a not-yet-real observation confirmed at
info, labeled future-fragility") measurable with this same harness.

## Recommendation (pending JF adjudication)

> **Resolved 2026-07-15:** JF ratified both conversion rows; #124 merged as
> measured (no post-A/B prompt edits). See the ruling addendum below.

Merge the rubric change. The delta is exactly the ruled shape: target-class
conversions occur (2), carry correct mechanisms, and nothing else moves
beyond the control floor; uncertainty drops without confirm-side loss;
cost is neutral-to-cheaper. Rows 1–2 are the items to ratify or veto; rows
3–5 document the open boundary without deciding it.

## Cost

Anthropic API (not Max quota): control ≈ 1.10M in / 55K out; A/B ≈ 1.06M in /
53K out. Raw JSONs in the session scratchpad; this report is the evidence of
record.

## Ruling addendum — 2026-07-15 (JF adjudication)

Both conversion rows **RATIFIED confirmed@info**; the rubric change merges
as measured.

**Row 1 (`llm/tokens.py:102`) — ratified, with two boundary rulings:**

1. **The intent boundary is declared-vs-derived, not human-vs-machine.**
   Intent-documented behavior fails Reality only when the intent is
   *declared* in the artifact — comments, docstrings, identifier names,
   human-maintained docs, referenced external contracts. Who (or what)
   typed the declaration is irrelevant; most of this artifact is
   machine-authored, and a generated docstring is still a declaration by
   the author-of-record. Two dismissal routes are invalid — both
   self-referential ("self-licking ice cream cones", JF):
   - **Derived artifacts never constitute intent.** Shadow docs are
     produced by observing the code and cannot, by construction, contradict
     it — that is the point of shadow docs. They may *relay* a declaration
     (quote a docstring, point at an external contract) but their own
     description of behavior is not documentation of design intent.
     (ab-v15e items 3/4 show the old rubric using "shadow-doc-documented"
     as dismissal grounds — the observed failure mode.)
   - **Code shape is not a declaration.** "Someone typed `< 10_000`, so
     someone meant it" never fails Reality. Code is not documentation.

   Rubric clarification filed as osojicode/work#64 (one-variable prompt
   change + A/B when scheduled; note side B produced the correct verdict on
   this row without such language — the hazard was only observed under the
   old rubric).

2. **Grade severity against the tool's deployment context, not the dogfood
   repo.** The cap binds at ~5K files (stats counts source + shadow text
   per file) — well inside the target repo population even though osoji
   itself never gets there. JF: "clearly a flaw." Remediation (named
   constant + LRU eviction) ships as a separate PR.

**Row 2 (`tests/test_prompt_regression.py:457`) — ratified.**
Character-identical helper bodies are a falsifiable redundancy observation,
inside decisions/0018's consistency boundary; surfaces at info.

Byproduct: osojicode/work#65 (parked) — name-as-claim contradiction
candidates (`upper_limit` used as a lower bound): commission-class, the
identifier-scope cousin of work#60's declared-principles idea.

The unruled boundary (rows 3–5, whether future-fragility notes surface at
info) remains unruled and untouched.
