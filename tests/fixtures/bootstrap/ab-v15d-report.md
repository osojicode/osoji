# V1-5d A/B report: doc accuracy, legacy verify pass vs unified Triage (per-file description gaps)

**Ticket:** osojicode/work#31 · **Branch:** `v1-5d-doc-per-file` · **Date:** 2026-07-04/05

## Design

Same-tree pipeline A/B per decision 0016 (frozen `origin/main` @ `a906f3f`, one `.osoji` copy,
`PYTHONPATH` swap):

```
PYTHONUTF8=1 PYTHONPATH=<side>/src python -c "from osoji.cli import main; main()" \
    audit . --exclude shadow,debris --no-fix --format json
```

**With a variance control**: the legacy side ran twice (A1, A2) because doc analysis is
stochastic at the propose stage — the control turned out to be the most important measurement
in the gate.

## Headline

| | legacy A1 | legacy A2 (same code) | branch B1 | branch B2 (post boundary-fix) |
|---|---|---|---|---|
| doc findings | 12 (6 error / 6 warning) | 11 | 4 (all warning) | 2 (1 error / 1 warning) |
| coverage-class FPs | several ("does not mention") | several | 2 (README) | **0** |

**Variance result:** only 2 of 12 findings recur verbatim between the two identical legacy
runs (~83% churn); semantically, the solid accuracy issues recur reworded while the dated
design-doc cluster (4 findings) vanished entirely. Conclusion: single-shot A/B deltas cannot
attribute individual doc findings; the propose stage (unchanged by this migration) dominates.

## Adjudication (all 14 A1↔B1 deltas, against source truth)

- 7 removals correct: the dated design-doc cluster (historical records, true-at-writing) and
  CLAUDE.md coverage-class findings — exactly the FP modes the migration targets.
- 4 "suppressed TPs" investigated: the two solid ones (tutorial `CheckResult.passed` semantics;
  the LiteLLM provider-list claim) **recur in legacy A2 and the LiteLLM class is confirmed by
  branch B2** — and the B2 interaction log (19 MB) contains **zero model-output mentions** of
  the CheckResult claim: the legacy propose stage never surfaced it that run. Attribution:
  legacy propose churn, not triage suppression.
- B1's 2 additions were coverage FPs on README — the boundary leak that motivated the deeper
  fix below. B2 (post-fix) emitted zero coverage findings.

## Deeper fix: accuracy/coverage boundary

The description-gap rubric section now opens with the mission boundary: a description gap
requires a **positive assertion the code contradicts**; absence-of-mention is a coverage
question owned by a different subsystem and is dismissed regardless of usefulness. Wording
verified to preserve negatively-phrased contradictions (a claimed-exhaustive list with a
missing item is an assertion, not an omission). Routing pinned by a canned-verdict test.

Known follow-up (deliberately out of scope, one-variable discipline): the legacy
`_ANALYZE_SYSTEM_PROMPT` is internally contradictory — it states the boundary but also
invites omission findings at warning severity. The triage gate now enforces the boundary
regardless; the propose-prompt cleanup is a separate measured change.

## Corpus re-check (7 doc slugs, claim mode)

5/7 agree, plus two attributed non-agreements:
- `audit-doc_stale_content-000` dismissed vs adjudicated-confirmed: the finding is a
  "CLAUDE.md doesn't mention the V1 modules" coverage claim — the dismissal is the boundary
  principle **working as designed** against a V1-4-era label that predates the mission split.
  Corpus label queued for re-adjudication in the V1-7 refresh.
- `audit-doc_incorrect_content-000` uncertain vs confirmed: the evidence window omitted the
  doc line the claim quotes; the model honestly declined to confirm what it could not see.
  Ships as a warning under this branch's verdict policy (uncertain → warning with reasoning).
  Follow-up: snippet-anchoring should include the claim's quoted text region.

## Verdict policy

Suppress only `dismissed`; `uncertain` kept at warning severity with triage reasoning attached
(Phase 3 debris precedent + signal conservation). Confirmed findings may regrade severity from
the verdict; a verdict without severity preserves the original.

## Real doc bugs surfaced (tracked for a docs PR on main, independent of this migration)

Tutorial `CheckResult.passed` omits the `and not self.errors` condition; CLAUDE.md and
CHANGELOG still reference LiteLLM (providers use direct SDKs); `osoji-sweep.md` endpoint
priority omits `.osoji.local.toml`; SUPPLY-CHAIN-SECURITY.md hook description drift.
