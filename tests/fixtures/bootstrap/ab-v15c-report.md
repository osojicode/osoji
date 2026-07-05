# V1-5c A/B report: obligations, pure heuristic vs unified Triage (file-tuple contracts)

**Ticket:** osojicode/work#30 · **Branch:** `v1-5c-obligations-file-tuple` · **Date:** 2026-07-04/05

## Design

Same-tree pipeline A/B per decision 0016: one worktree pinned at `origin/main` @ `a906f3f`,
one `.osoji` artifact copy (pristine-restored between runs), pipeline code varied via
`PYTHONPATH`:

```
PYTHONUTF8=1 PYTHONPATH=<side>/src python -c "from osoji.cli import main; main()" \
    audit . --obligations --exclude shadow,doc-analysis,debris --no-fix --format json
```

Unlike the other migrations, side A (legacy) is **zero-LLM**: Phase 3.5 was a pure heuristic
with no judgment layer. This migration *adds* LLM Triage where none existed — the A/B measures
what the new filter keeps and kills, plus the new LLM cost.

## Headline

| | main (heuristic only) | branch, first cut | branch, final (clustered) |
|---|---|---|---|
| obligation findings shipped | 212 (2 violation + 210 implicit) | 30 | 30 (one per **distinct contract**) |
| contract_class distribution | — | 28 unnamed / 2 named | 27 unnamed / 3 named |
| CE-gap (`other`) rate | — | 0 | 0 |
| LLM cost | 0 | ~18 batches | fewer claims (clusters ≈ half the pair-findings) |

Both legacy `violation` findings adjudicated as heuristic FPs (false "never produced" premises).

## The gate loop (three measured iterations)

1. **First cut** (adapter + Triage): corpus 8/10 — both V1-4 residuals (003 pair-misattribution,
   007) fixed by this branch's attribution work; two NEW misses (001, 002): bundled multi-literal
   claims dismissed by per-literal ecosystem anchoring.
2. **Bundle-aggregation principle** added (judge a bundle by its strongest constituent).
   Independent adjudication of a 14-dismissal stratified sample: 10 correct, 4 suppressed TPs,
   systematic cause identified — near-duplicate pair-findings of the same contract triaged
   independently, sometimes losing every representative.
3. **Contract-level clustering with representative guarantee** (`_cluster_by_contract`): one
   canonical claim per distinct contract `(finding_type, frozenset(values))`, anchored at the
   best-attested pair, all sites in evidence; a contract can now be dropped only by an explicit
   verdict on a claim that represents it. Plus a protocol-vocabulary consistency principle.

Final live run: both bundle-family suppressed TPs **recovered** (config-source Literal family;
doc-coverage enums, now anchored at their true home). The remaining two sample losses
adjudicated as non-losses: one weak single-literal claim, and the orphaned-files "drift" —
whose dismissal reasoning correctly identifies the test as asserting properties on the real
class (loud coupling, not a silent contract).

## Corpus re-adjudication (2026-07-05, project owner)

Final corpus: **9/10** under re-adjudicated labels.
- `audit-obligation_implicit_contract-002` relabeled **dismissed**: claudeMdExcludes/end_turn are
  Anthropic CLI/API vocabulary; the claude-code pairing is a test asserting `.name` — the
  assertion is the loudness mechanism. (V1-4 label predated the protocol-vocabulary principle.)
- `audit-obligation_implicit_contract-001` **re-affirmed confirmed**: default_provider/OSOJI_TOKEN
  are project-owned names with non-test consumers. Ships as the known 9/10 disagreement;
  V1-7 note: the ideal anchor is the init.py↔config.py pair.

## Measurement caveat (methodological, recorded for V1-7)

One dismissal reasoning cited the committed bootstrap manifest's own adjudication note as
evidence — the repo-wide sweep sees the committed corpus (decision 0016's corollary in a new
form: adjudication text can leak into reasoning on osoji-on-osoji runs). Verdicts on other
repos are unaffected; corpus design must assume sweep visibility.

## Deferral debts closed by this branch

- Prefixed/unprefixed category reconciliation (obligation half of the CE-gap): persisted
  `obligation_{finding_type}` categories now map to `gap_type="contract"`; previously-unreachable
  `CLAIM_BUILDER_SCHEMA` keys resolve.
- Residual `audit-obligation_implicit_contract-003`: `_check_fragility` emitted the cartesian
  product of producers×checkers; now one finding per (checker, value) named by the
  import-linked producer. Corpus 003 and 007 both agree post-fix.
- New: optional `contract_class` verdict enum with an explicit `other` outlet; the CE-gap rate
  (other-proportion over all classified claims, dismissed included) is the taxonomy-adequacy
  metric per the closed-set-taxonomy principle.
