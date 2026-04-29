---
id: "0003"
title: Self-sufficient claims and the Claim Builder
type: concept
status: draft
created: 2026-04-29
updated: 2026-04-29
related: [concepts/three-gap-theory.md, concepts/string-contract-taxonomy.md, specs/0001-v1-foundation.md]
---

## The problem this solves

A naive Triage architecture gives the LLM a finding plus tool access (grep, read, list) and lets it explore the codebase to decide. Token cost is unbounded — it scales with how aggressive the LLM is at exploration. For a codebase of nontrivial size, this becomes the dominant audit cost and the dominant audit latency.

A **self-sufficient claim** is a structured object that contains everything Triage needs to apply the [TP-predicate rubric](three-gap-theory.md#the-frame) — case-for, case-against, positional context, relevant shadow docs — assembled mechanically before Triage runs. Triage decides each claim in one LLM call without exploration. Token cost becomes bounded and predictable; it scales linearly with finding count.

This is the same insight gepa formalizes for general agentic optimization: rich traces beat scalar rewards because the reasoner doesn't need to retrieve. Applied at the Triage layer, the principle is **mechanical layers gather; LLM layers reason**. The boundary is empirical (decided per-finding-class by what the Claim Builder bootstrap shows the LLM actually consults) and revisable.

## What goes in a claim

A claim's structure is the [Finding schema](../specs/0001-v1-foundation.md#the-finding-schema-a) plus a richer Evidence list. Conceptually:

```
Hypothesis:
  gap_type, contract_claim, observed_behavior, location

Evidence FOR (case for confirming):
  - "no references to `foo` in any of N files indexed in FactsDB"
  - "literal `failed` in test/test_x.py:45 (assert) and src/y.py:12 (raise)"
  - "docstring claims sorted output; function uses set() which is unordered"

Evidence AGAINST (case for dismissing):
  - "symbol `foo` appears in base class `BaseHandler` — possible interface dispatch"
  - "literal `404` appears with `status_code=` token, in function called `handle_response`"
  - "function is registered via `@route` decorator at line 8"

Positional context (without semantic interpretation):
  - "literal in stdlib constants set: yes / no / unknown"
  - "name pattern matches a framework convention (positional flag, not verdict): yes / no"
  - "surrounding 5 lines of code"
  - "enclosing function signature"

Relevant shadow docs (compressed-code Evidence):
  - <file>.shadow.md (always)
  - _directory.shadow.md (when potentially architectural)
  - _root.shadow.md (when potentially project-level)

Open questions Triage must answer:
  - "does the AGAINST evidence plausibly explain the zero-reference signal?"
  - "is this literal class 1, 2, 3, 4, or 5 per string-contract-taxonomy?"

Insufficient-evidence flag:
  - if the Claim Builder cannot fill required Evidence kinds, flag the claim
    so Triage escalates to exploration mode rather than guessing.
```

## Division of labor: positional vs semantic

The Claim Builder produces **positional** evidence — where in the code does this literal/symbol/comment live, what's around it, what's its enclosing function or module. The LLM provides **semantic interpretation** — what 404 *means*, whether a particular framework registration is real, whether two surrounding contexts are about the same concept.

This division is load-bearing. The mechanical layer is *deliberately* ignorant of stdlib semantics, RFC values, framework conventions. Any attempt to embed such knowledge mechanically recreates the catalog anti-pattern (see [pipeline engineering principles](../../CLAUDE.md#pipeline-engineering-principles)) at the evidence-gathering layer. The LLM has world knowledge in its weights; the Claim Builder positions the artifact so that knowledge can fire.

Concrete example: an Evidence kind `surrounding_code_context` (here are the 5 lines around the literal, plus the enclosing function signature) is doing more semantic work than a kind `is_http_code: bool`. The first composes with LLM knowledge; the second tries to encode it.

## Shadow docs as the primary compressed-code substrate

osoji already maintains a three-tier shadow doc layout (`<file>.shadow.md`, `_directory.shadow.md`, `_root.shadow.md`) — the digested form of code at three scopes. Self-sufficient claims include the relevant shadow docs as Evidence rather than raw source.

| Substrate | Token cost | Fidelity | When to include |
|---|---|---|---|
| Raw source | High | Full | Only when shadow doc loses critical detail (rare; flagged via insufficient-evidence) |
| `<file>.shadow.md` | Low | Structural | Always |
| `_directory.shadow.md` | Low | Architectural | When a potential description gap could be architectural |
| `_root.shadow.md` | Low | Project-level | When a potential description gap could be project-level |

This makes shadow docs the *primary* Evidence kind for most findings. It also amortizes osoji's existing investment in shadow generation — the most expensive thing osoji already does is reused as Triage input rather than discarded after detector candidate filtering.

## Bootstrap path

We don't claim a priori to know what evidence is sufficient for each finding category. We measure.

1. **Observe.** Run Triage in *exploration mode* on a small representative set — give the LLM read/grep/list tools, let it decide. Log every tool call: what was grep'd, what was read, what was concluded.
2. **Mine.** Analyze the traces. For each finding category, what Evidence kinds did the LLM consistently consult? Patterns emerge: `dead_code` always involved cross-file references, base class hierarchy, and string-literal occurrences of the symbol name; string-contract candidates always involved surrounding-code context plus the sibling file's surrounding code.
3. **Mechanize.** Build the Claim Builder to produce exactly those Evidence kinds, using only successful (correct-verdict) exploration traces as the spec. The LLM's exploration becomes the *requirements doc* for the mechanical layer.
4. **Validate by ablation.** Run Triage in claim-only mode against the same set. If verdicts match the exploration baseline, mechanization is sufficient. If they diverge, a missing Evidence kind explains the gap. Add it; repeat.

Two subtleties worth being explicit about: only mine *correct* exploration traces (the LLM sometimes wanders into hallucinated paths and we don't want to mechanize bad exploration), and refresh the bootstrap periodically as the [sweep → fixture corpus](../specs/0001-v1-foundation.md#sweep--fixture-corpus-c-data) on new codebases surfaces new failure modes. Patterns mined from osoji-on-osoji may not generalize.

## Escalation path

When the Claim Builder cannot fill a required Evidence kind — a referenced file is missing, a symbol's facts are malformed, a contract's sibling file is outside the indexed scope — the claim carries an `insufficient_evidence` flag. Triage handles this by escalating to exploration mode for that single claim: the LLM gets tool access and decides with retrieval. Cost stays bounded because the escalation rate is itself a metric and most claims resolve one-shot.

The escalation rate is also a quality signal on the Claim Builder. A rate that climbs over time signals the schema needs revision; the bootstrap loop runs again.

## Optimization (v2): gepa over the Claim Builder schema

There are two distinct optimization targets, cleanly separable:

- **Triage prompt** evolves how the LLM *reasons over* given evidence. Mutates the rubric, the rubric examples, the question framing.
- **Claim Builder schema** evolves *what evidence is gathered*. Mutates which Evidence kinds to include, how much surrounding context per kind, how to summarize.

Either can run gepa independently against the regression evaluator. They could even compete: a Claim Builder mutation that drops an Evidence kind shouldn't hurt verdict accuracy if the kind was non-load-bearing. That's *exactly* what gepa-style ablation is for. Over time, the Claim Builder converges to the minimum-sufficient evidence schema — which is also the cheapest token-wise.

This requires that the Claim Builder schema be a **configuration object** (a list of evidence-kind-builders to invoke per claim), not a hardcoded class, so gepa can mutate the list without code changes. Designed-for in v1; built in v2.

## Properties this gives osoji

- **Bounded token cost.** Audit cost = N × (avg claim size) × (per-token cost) + escalation surcharge. Predictable, capacity-planneable.
- **Auditable reasoning.** Every verdict is traceable to a structured claim. The "why did osoji say this is dead code?" question has a complete answer in the claim record.
- **Reproducible reasoning.** Same claim → same decision (modulo LLM stochasticity, which the regression framework already measures).
- **Honest evidence schema.** What's in a claim is what we *measured* the LLM uses, not what we *guessed* it should.
- **Optimizable.** The schema itself is a gepa target.
- **Empirically grounded.** Falsifiable at every layer: claims that triggered escalation tell us where the schema is incomplete; verdict-disagreement between claim-mode and exploration-mode tells us how good the mechanization is.

## Open questions

- **Bootstrap test set composition.** Should it be osoji-on-osoji only, or include sweep results from diverse projects? Probably a mix; resolve when the first bootstrap runs.
- **Claim batch size for Triage.** How many self-sufficient claims fit in a single LLM call before context-window or attention degradation hurts? Empirical; benchmark during step 3 of the v1 order of operations.
- **Per-Evidence-kind weighting.** Should the schema configuration include a weight hint per Evidence kind (already a field in the v1 `Evidence` dataclass), or let the LLM weight implicitly? The honest answer is probably "let the LLM weight; remove `weight_hint` if measurement shows it's unused."
- **What's the minimum-sufficient claim format for ablation?** When gepa drops Evidence kinds, what's the floor below which decisions degrade? Will tell us which kinds are doing real work.
