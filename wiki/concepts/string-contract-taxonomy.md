---
id: "0002"
title: String-contract taxonomy
type: concept
status: draft
created: 2026-04-29
updated: 2026-04-29
related: [concepts/three-gap-theory.md, concepts/self-sufficient-claims.md, specs/0001-v1-foundation.md]
---

## Why a taxonomy

Hard-coded strings and literals are the most common false-positive class in current osoji. The `obligations.py` detector runs as pure-Python pattern matching — no LLM filter — and treats every shared literal as a potential contract. This conflates several distinct semantic classes, each requiring different Triage logic.

This page defines the rubric Triage applies when reasoning about literal-based findings. It is **not** detector logic. The detector continues to enumerate candidate shared literals via cheap pattern matching; classification happens in Triage with the LLM, with mechanically-assembled evidence as input.

## The five classes

| Class | What it looks like | Real contract? | Failure mode if drift | Triage response |
|---|---|---|---|---|
| **Named project obligation** | One file declares a constant (`MAX_RETRIES = 3`); another file uses the bare literal in a semantically-related context (`if attempts < 3`). The constant has a name; the literal is duplicating it. | **Yes** | Drift produces silent disagreement | Confirm; suggest `if attempts < MAX_RETRIES` |
| **Unnamed project obligation** | Two files use the same bare literal in clearly-related semantic roles (both look like retry counts), but no shared constant exists yet. | **Yes** (latent) | Drift produces silent disagreement | Confirm; suggest extracting a shared constant |
| **Ecosystem convention** | A literal whose meaning is defined *outside* the project: HTTP codes (`200`, `404`), file modes (`0o644`), DNS port (`53`), MIME types (`"application/json"`), Unix signals, RFC-defined strings, language-version literals. | **No** — the contract is with the external standard, not within the project | None — both endpoints reference the standard independently | Dismiss with reasoning: standard external value |
| **Magic-constant duplication (ambiguous)** | A literal repeats across files, the surrounding code is *not* clearly the same concept, but it isn't obviously coincidental either. | **Sometimes** | Possible silent disagreement; possibly nothing | Examine: if the two sites *should* agree, confirm; if coincidence, dismiss |
| **Coincidental duplication** | The same literal appearing in test fixtures and production code, or in unrelated semantic roles (`user_id = 12345` in a test; `12345` in a numeric calculation). | **No** | None | Dismiss as coincidence |
| **Other** | Doesn't fit any class. | — | — | Route to the broadest-context Triage with explicit "uncategorized" verdict reasoning. Counts toward the [CE-gap metric](#how-this-taxonomy-is-used). |

Hybrid classifications are legitimate. A literal that is *both* an ecosystem convention *and* a named project obligation (e.g., a project defines `STATUS_NOT_FOUND = 404` and uses it via the named constant) gets classified to both classes; Triage's response is the conjunction (confirm the named-obligation aspect; dismiss the bare-`404` complaint). The Finding schema accommodates a list of class hypotheses, not a single label.

## Why pure-rule matching can't decide

A rule that flags every shared literal will flag standard HTTP codes (`200` appearing in three handler files) just as readily as it flags real project obligations. The literal pattern is identical; only the semantic status differs, and that status requires general knowledge ("404 is a standard HTTP code defined in RFC 7231") that a pure-rule check does not possess.

This is the structural reason the v1 plan routes obligations through the unified [Triage stage](../specs/0001-v1-foundation.md#the-triage-stage-b). Triage receives mechanical positional evidence (the literal, its surrounding code, sibling occurrences) and applies its general knowledge to classify. The rubric above is what Triage's prompt encodes.

This is **not** a claim that "mechanical filters never decide" as a general principle — that would be a slogan. It is an empirical observation that for *literal-based contract findings*, the world knowledge required to distinguish project-internal contracts from ecosystem conventions is stored in the LLM's weights, not in any feasible rule database. Other parts of osoji's pipeline are happy to be purely mechanical (file walking, hashing, AST parsing). The boundary is empirical, decided per-task.

## What the detector does and doesn't do

The string-contract detector (file-tuple class per [three-gap minimum context](three-gap-theory.md#minimum-context-invariants)):

- Continues cheap pattern matching to enumerate **candidate** shared literals across file pairs. Cheap candidate filtering is fine.
- Attaches per candidate, via the [Claim Builder](self-sufficient-claims.md): the originating file/site, the consuming file/site, the surrounding code in both, and any positional signals that might inform classification (e.g. "literal is preceded by `status_code=`," "literal appears in a function called `handle_response`"). **Positional, not semantic.** The detector does not pre-classify; it presents the dossier.
- **Never** emits a finding directly. Pure-rule emission is the failure mode this taxonomy exists to prevent.

Triage applies the rubric and produces a finding (with verdict, confidence, reasoning) for each class-1 / class-2 case and contested class-4 cases. Class-3 and class-5 cases are dismissed at Triage with reasoning recorded.

## How this taxonomy is used

This is a **descriptive taxonomy** (used as Triage rubric vocabulary), not a dispatch taxonomy. Two implications for falsifiability:

- **CE-gap rate**: proportion of literal-based findings classified as `other`. If this rises above ~5% on a representative corpus, the taxonomy is missing a class.
- **ME-overlap is acceptable** because Triage routes hybrids to multi-class responses, not to multiple analysis pipelines. A high overlap rate isn't a failure mode; the rubric is robust to it.

These metrics live alongside per-detector TP/FP in the [prompt regression evaluator](../specs/0001-v1-foundation.md#sweep--fixture-corpus-c-data).

## Open questions

- **How aggressive should the candidate filter be?** A purely permissive filter (every literal repeated across files) over-feeds Triage and burns LLM tokens; a heuristic skip-list (numeric literals < 10, single-character strings) is the kind of catalog the [pipeline engineering principles](../../CLAUDE.md#pipeline-engineering-principles) warn against. The honest answer is probably "permissive filter + Triage rubric does the work," monitored by the regression evaluator. Resolve when Claim Builder schema is implemented.
- **Should Evidence carry a `class_hypothesis` field?** A pre-Triage classifier that proposes a class (informed by the literal's shape, location, and surrounding code) could speed Triage. Defer until the unclassified-Triage baseline is measured per the [self-sufficient claims bootstrap path](self-sufficient-claims.md#bootstrap-path).
- **Do version strings (`"v1"`, `"2.4.1"`) form a sixth class?** They look ecosystem-convention-ish but are project-specific. Catalog cases when they appear; promote to class if pattern emerges.

## Why this matters

This taxonomy is the wedge for the longstanding complaint that osoji "likes seeing strings produced one place and consumed elsewhere" without a coherent model for what makes a real problem. The five classes give Triage a defensible rubric: project-originated obligations get confirmed (with the named/unnamed split governing the suggested fix); ecosystem conventions get dismissed; ambiguous cases get reasoned about case-by-case rather than swept either way. The classes are descriptive — used to articulate verdicts, not to gate analysis — so non-MECE among them is acceptable and doesn't corrupt behavior.
