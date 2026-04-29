---
id: "0001"
title: Three-gap theory
type: concept
status: draft
created: 2026-04-29
updated: 2026-04-29
related: [specs/0001-v1-foundation.md, concepts/string-contract-taxonomy.md, concepts/self-sufficient-claims.md]
---

## The frame

Every code-quality finding in osoji is a hypothesis about a **gap** between what the code claims and what the code does. There are three gap types, and every existing osoji detector maps onto one (with an explicit `uncategorized` outlet for findings that don't fit — see [How this taxonomy is used](#how-this-taxonomy-is-used-and-what-would-make-it-wrong) below).

| Gap type | What's claimed | What actually happens | Existing detectors |
|---|---|---|---|
| **Reachability** | declared / claimed to be used | unreachable | `dead_code`, `dead_symbol`, `dead_parameter`, `unactuated_config`, `orphaned_file`, `unused_dependency` |
| **Description** | described one way (comment, docstring, name, type) | behaves another | `stale_content`, `incorrect_content`, `misleading_claim`, `stale_comment`, `latent_bug` (when it violates a stated type/contract) |
| **Contract** | implicit cross-component agreement (shared string, schema, ABI) | broken | `obligation_violation`, cross-file string drift, `latent_bug` (when it violates an implicit invariant), schema/ABI mismatch |
| **Uncategorized** | (does not fit cleanly) | — | safety valve; routed to broadest-context Triage and counted as a metric on taxonomy adequacy |

A finding is a true positive iff three predicates hold:

- **Reality** — the gap exists in the actual code.
- **Significance** — the gap matters (closing it improves the codebase; widening it would harm).
- **Actionability** — there is a concrete fix.

The unified [Triage stage](../specs/0001-v1-foundation.md#the-triage-stage-b) is an evidence-weighted verifier of these three predicates. Every detector becomes a *gap proposer*; Triage becomes a *gap verifier*.

This frame generalizes cleanly to absorb tree-sitter queries, OSS scanner output (semgrep, ruff, bandit, gosec, eslint), and any future detector — they all produce gap hypotheses; all flow through the same Triage.

## Minimum-context invariants

Each gap type has a **minimum propose-time context** below which proposals are structurally false-positive-prone. Conflating these contexts — running every detector against the same per-file substrate — has been a structural source of FPs in current osoji.

| Gap type | Minimum propose-time context | Why |
|---|---|---|
| **Reachability** | **Project-graph context** | A file in isolation can at best say "no references appear in this file." That's the perspective that produces FPs when a symbol is referenced via dynamic dispatch, dataclass→asdict chains, framework registration, or implicit re-exports. The FactsDB is the project graph; today it is consulted at filter and triage time but not at *propose* time, which is the wrong gate. |
| **Description** | **Smallest sufficient shadow scope** (file / directory / root) | A claim can drift relative to its adjacent code, its directory's pattern, or the project's architecture. The right propose-time context is the smallest shadow scope that contains both the claim and the candidate-violating behavior. See [Description gap scope spectrum](#description-gap-scope-spectrum) below. |
| **Contract** | **File-tuple context** | The N files (typically two) sharing an implicit or explicit contract. `obligations.py` already groups by file pair; the rest of the contract-gap detectors should follow. |

Detectors that need broader context than their declared window — for instance, a contract detector that wants to confirm a third file is unaffected — declare it explicitly via the [Evidence schema](../specs/0001-v1-foundation.md#the-finding-schema-a) rather than reaching for ambient access. Triage retains global cross-file capability as a safety net, but the goal is to stop generating doomed findings at the source rather than relying on Triage to catch them after the LLM has already committed to a context-blind perspective.

### Description gap scope spectrum

Description gaps are not all local. Three sub-cases the detector must distinguish:

- **Local description drift** — a comment or docstring claims X about the function or class immediately around it; per-file context (`<file>.shadow.md`) is sufficient. Examples: `# returns sorted list` above a function that no longer sorts; a docstring describing parameters that have since been renamed.
- **Architectural description drift** — a module-level docstring or directory README claims a pattern that the rest of the directory has since deviated from. Needs `_directory.shadow.md` plus the file. Examples: a `_handlers.py` docstring says "all handlers register via `@route`, no exceptions" but a sibling file added an exception.
- **Project-level description drift** — a top-level README, architecture doc, or `_root.shadow.md` claim that components elsewhere now violate. Needs `_root.shadow.md`. Examples: README says "stateless workers" but one worker now caches per-request state; contributing guide claims "all detectors are language-agnostic" but a new one hardcodes Python conventions.

osoji's existing three-tier shadow doc layout is the right substrate. Per-file detectors that propose description gaps should consume the *smallest* scope that brackets both the claim and a candidate-violating behavior — not the largest. Larger scopes invite hallucinated drift; smaller scopes miss architectural-level claims. Triage retains broader scopes as a safety net.

## How this taxonomy is used (and what would make it wrong)

Three-gap theory serves two distinct uses, and the falsifiability metric is different for each.

- **Generative use** — the taxonomy frames what osoji is looking for. A finding that doesn't fit any gap type is either out of scope (osoji doesn't aim to detect it) or a signal that the taxonomy is missing a category. **Falsified by CE-gap rate**: the proportion of findings classified `gap_type=uncategorized`. If this rises above ~3% on a representative corpus, the taxonomy is missing a category.
- **Analytical use** — the gap_type dispatches a finding to the right minimum-context detector class. Two findings classified into different gap types should require different analysis pipelines. **Falsified by ME-overlap rate**: the proportion of findings that legitimately fit multiple gap types and require analyses from more than one minimum-context class. Some overlap is acceptable (e.g., `latent_bug` straddling description/contract by classification rule); structural overlap signals the dispatch boundary is wrong.

Both metrics are tracked alongside per-detector TP/FP rates by the [prompt regression evaluator](../specs/0001-v1-foundation.md#sweep--fixture-corpus-c-data). The taxonomy is treated as a falsifiable engineering claim, not a theorem.

## Why this matters

Before three-gap: each detector independently decided what "wrong" means; six different verification gates, six schemas, six surfaces to debug. Improving any one of them did nothing for the others.

After three-gap: one definition of true-positive, one rubric, one Triage stage. Improving the rubric improves every detector. The propose-time minimum-context invariant directly attacks the FP class the user has been fighting. The `uncategorized` outlet plus CE-gap and ME-overlap rates make the taxonomy honestly falsifiable rather than asserted.

## Relation to other terms in the wiki

- The [Finding schema](../specs/0001-v1-foundation.md#the-finding-schema-a) carries `gap_type` as a typed field with an `uncategorized` value; this is its source of truth.
- The [Triage stage](../specs/0001-v1-foundation.md#the-triage-stage-b) consumes findings and applies the three-predicate verification.
- [Self-sufficient claims](self-sufficient-claims.md) is the mechanism by which evidence reaches Triage.
- [String-contract taxonomy](string-contract-taxonomy.md) is the sub-taxonomy Triage uses when reasoning about contract gaps over hard-coded literals.

## Open questions

- **Do all `latent_bug` variants fit cleanly into "description" or "contract"?** The current rule splits them by whether the violated invariant is *stated* (description) or *implicit* (contract). There are likely edge cases — e.g. a violated type hint that exists only at runtime via `__class__` checks — that could go either way. Catalog cases as they appear; the `uncategorized` outlet absorbs unclear ones until the rule is refined.
- **Tree-sitter queries: are they detectors, or evidence sources?** Probably both, depending on how the query is wired. A query that says "every public function named `_foo`" is a detector (proposes findings); a query that says "every call site of this function" is evidence (consumed by reachability detectors). The Finding schema doesn't need to distinguish; the wiring layer does.
- **Is project-graph context sufficient for reachability gaps in the presence of dynamic dispatch / metaprogramming?** Probably not at the limit. Defer until measurement shows it matters.
