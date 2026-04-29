---
id: "0001"
title: Three-gap theory
type: concept
status: draft
created: 2026-04-29
updated: 2026-04-29
related: [specs/0001-v1-foundation.md]
---

## The frame

Every code-quality finding is a hypothesis about a **gap** between what the code claims and what the code does. There are three gap types, and every existing osoji detector maps cleanly onto one.

| Gap type | What's claimed | What actually happens | Existing detectors |
|---|---|---|---|
| **Reachability** | declared / claimed to be used | unreachable | `dead_code`, `dead_symbol`, `dead_parameter`, `unactuated_config`, `orphaned_file`, `unused_dependency` |
| **Description** | described one way (comment, docstring, name, type) | behaves another | `stale_content`, `incorrect_content`, `misleading_claim`, `stale_comment`, `latent_bug` (when it violates a stated type/contract) |
| **Contract** | implicit cross-component agreement (shared string, schema, ABI) | broken | `obligation_violation`, cross-file string drift, `latent_bug` (when it violates an implicit invariant), schema/ABI mismatch |

A finding is a true positive iff three predicates hold:

- **Reality** — the gap exists in the actual code.
- **Significance** — the gap matters (closing it improves the codebase; widening it would harm).
- **Actionability** — there is a concrete fix.

The unified [Triage stage](../specs/0001-v1-foundation.md#the-triage-stage-b) is an evidence-weighted verifier of these three predicates. Every detector becomes a *gap proposer*; Triage becomes a *gap verifier*.

This frame generalizes cleanly to absorb tree-sitter queries, OSS scanner output (semgrep, ruff, bandit, gosec, eslint), and any future detector — they all produce gap hypotheses; all flow through the same Triage.

## Minimum-context invariants

A second invariant the theory imposes: **each gap type has a minimum propose-time context** below which proposals are structurally FP-prone. Conflating these contexts — running every detector against the same per-file substrate — has been a structural source of FPs in current osoji.

| Gap type | Minimum propose-time context | Why |
|---|---|---|
| **Reachability** | **Project-graph context** | A file in isolation can at best say "no references appear in this file." That's the perspective that produces FPs when a symbol is referenced via dynamic dispatch, dataclass→asdict chains, framework registration, or implicit re-exports. The FactsDB is the project graph; today it is consulted at filter and triage time but not at *propose* time, which is the wrong gate. |
| **Description** | **Per-file context** | The file containing the claim and the file containing the behavior, usually the same file. Per-file reading is the right window for stale comments, misleading docstrings, and latent bugs that can be ruled in or out from a function body alone. Shadow-doc-style isolation is a feature here, not a bug. |
| **Contract** | **File-tuple context** | The N files (typically two) sharing an implicit or explicit contract. `obligations.py` already groups by file pair; the rest of the contract-gap detectors should follow. |

Detectors that need broader context than their declared window — for instance, a contract detector that wants to confirm a third file is unaffected — declare it explicitly via the Evidence schema rather than reaching for ambient access. Triage retains global cross-file capability as a safety net, but the goal is to stop generating doomed findings at the source rather than relying on Triage to catch them after the LLM has already committed to a context-blind perspective.

## Why this matters

Before three-gap: each detector independently decided what "wrong" means; six different verification gates, six schemas, six surfaces to debug. Improving any one of them did nothing for the others.

After three-gap: one definition of true-positive, one rubric, one Triage stage. Improving the rubric improves every detector. The propose-time minimum-context invariant directly attacks the FP class the user has been fighting.

## Relation to other terms in the wiki

- The [Finding schema](../specs/0001-v1-foundation.md#the-finding-schema-a) carries `gap_type` as a typed field; this is its source of truth.
- The [Triage stage](../specs/0001-v1-foundation.md#the-triage-stage-b) consumes findings and applies the three-predicate verification.
- The [Evidence model](../specs/0001-v1-foundation.md#evidence-gathering) records, per Evidence kind, what a piece of evidence contributes to which predicate.

## Open questions

- **Do all latent-bug variants fit cleanly into "description" or "contract"?** The plan splits them by whether the violated invariant is *stated* (description) or *implicit* (contract). There are likely edge cases — e.g. a violated type hint that exists only at runtime via `__class__` checks — that could go either way. Catalog cases as they appear.
- **Tree-sitter queries: are they detectors, or evidence sources?** Probably both, depending on how the query is wired. A query that says "every public function named `_foo`" is a detector (proposes findings); a query that says "every call site of this function" is evidence (consumed by reachability detectors). The Finding schema doesn't need to distinguish; the wiring layer does.
