---
id: "0001"
title: V1 Foundation — Unified Finding/Triage Architecture
type: spec
status: draft
created: 2026-04-29
updated: 2026-04-29
related: [concepts/three-gap-theory.md, decisions/0002-language-choice.md, specs/0002-wiki-bootstrap.md]
---

**Working title:** Foundation rebuild — unified Finding/Triage architecture, tree-sitter substrate, closed data loop.

## Context

osoji finds many useful things, but the user-visible signal-to-noise ratio is poor. 19+ open GitHub issues, almost all self-filed via the sweep skill, document false positives across nearly every detector. Fix history is mostly whack-a-mole: each commit patches a specific FP pattern (lambda factories, test fixtures, instance-method dispatch) without addressing root causes.

The diagnosis is structural, not tactical:

- **No theoretical basis for what counts as a finding.** Each detector independently decided what "wrong" means. There is no unifying frame that says "every osoji finding is a hypothesis about *X*."
- **No unified verification layer.** Phase 3 has its own LLM verification prompt; deadcode, deadparam, and plumbing each have their own; obligations has none. Six different gates, six different schemas, six independent surfaces to debug and improve.
- **No metric, no trainset, no learning loop.** The prompt-regression framework (`tests/test_prompt_regression.py`) catches degradation on 8 hand-built fixtures via binomial tests against established baselines — exactly the right substrate for an evaluator, but it is currently used only as a guard. The sweep skill produces structured TP/FP labels every run, but they are filed as GitHub issues rather than folded into a corpus.
- **Language-agnostic by intent, not by construction.** The CLAUDE.md principle "language agnosticism is non-negotiable" is undermined by hand-rolled Python and TypeScript AST plugins. Anything else — Rust, Go, Java — is unsupported.

The intended outcome of v1 is a foundation people can trust:

1. A theoretical frame that explains, in one sentence per detector, what each finding *is* and what makes it true or false.
2. One verification stage, one Finding schema, one rubric — so improving triage improves the whole system, not just one detector.
3. A working data loop: every sweep run produces fixture-quality training data; the prompt-regression harness becomes an evaluator, not just a guard.
4. Real language agnosticism via tree-sitter as the universal AST substrate.
5. A wiki-mediated workflow that preserves design rationale across sessions.

## Theoretical foundation: three-gap theory

Every code-quality finding is a hypothesis about a **gap** between what the code claims and what the code does. There are three gap types, and every existing osoji detector maps cleanly onto one:

- **Reachability gaps** — declared/claimed to be used; actually unreachable.
  Detectors: `dead_code`, `dead_symbol`, `dead_parameter`, `unactuated_config`, `orphaned_file`, `unused_dependency`.
- **Description gaps** — described one way; behaves another.
  Detectors: `stale_content`, `incorrect_content`, `misleading_claim`, `stale_comment`, `latent_bug` (when it violates a stated type/contract).
- **Contract gaps** — implicit cross-component agreement is broken.
  Detectors: `obligation_violation`, cross-file string drift, `latent_bug` (when it violates an implicit invariant), schema/ABI mismatch.

A finding is a true positive iff:

- **Reality**: the gap exists in the actual code.
- **Significance**: the gap matters (closing it improves the codebase; widening it would harm).
- **Actionability**: there is a concrete fix.

The unified Triage stage is an evidence-weighted verifier of these three predicates. Every detector becomes a *gap proposer*; Triage becomes a *gap verifier*.

This frame generalizes cleanly to absorb tree-sitter queries, OSS scanner output (semgrep, ruff, bandit, gosec, eslint), and any future detector — they all produce gap hypotheses, all flow through the same triage.

See [concepts/three-gap-theory.md](../concepts/three-gap-theory.md) for the standalone definition.

### Gap type → minimum context

A second invariant the theory imposes: **each gap type has a minimum propose-time context** below which proposals are structurally FP-prone. Conflating these contexts — running every detector against the same per-file substrate — has been a structural source of FPs in current osoji.

- **Reachability gaps** require **project-graph context**: who imports what, who calls what, who references what. A file in isolation can at best say "no references appear in this file," which is precisely the perspective that produces FPs when a symbol is referenced via dynamic dispatch, dataclass→asdict chains, framework registration, or implicit re-exports. The FactsDB is the project graph; today it is consulted at filter and triage time but not at *propose* time, which is the wrong gate.
- **Description gaps** require only **per-file context**: the file containing the claim and the file containing the behavior, usually the same file. Per-file reading is *the right window* for stale comments, misleading docstrings, and latent bugs that can be ruled in or out from a function body alone. Shadow-doc-style isolation is a feature here, not a bug.
- **Contract gaps** require **file-tuple context**: the N files (typically two) sharing an implicit or explicit contract. Obligations.py already groups by file pair; the rest of the contract-gap detectors should follow.

Triage continues to operate with global cross-file context as a safety net, but the goal is to stop generating doomed findings at the source rather than relying on triage to catch them after the LLM has already committed to a context-blind perspective.

## Architecture

### Detector context windows

Each detector declares its required propose-time context. Three classes:

- **Per-file detectors** read one source file plus the smallest shadow scope that brackets the claim and the candidate behavior — `<file>.shadow.md` for local drift, `_directory.shadow.md` for architectural drift, `_root.shadow.md` for project-level drift. See [description gap scope spectrum](../concepts/three-gap-theory.md#description-gap-scope-spectrum) for the three sub-cases. Right window for description gaps. Examples: `stale_comment`, `misleading_claim`, `latent_bug` when the bug is local, doc-accuracy errors. Shadow generation continues to feed these — shadow docs are repositioned as *the input to per-file detectors at the appropriate scope*, not as the universal substrate from which all findings are extracted.
- **Project-graph detectors** read FactsDB plus a candidate symbol's source file. Right window for reachability gaps. Examples: `dead_code`, `dead_parameter`, `unactuated_config`, `orphaned_file`, `unused_dependency`. These detectors must propose with cross-file reference data already in hand; today their LLM proposal step often runs file-local and then hopes verification will catch the FPs, which is the wrong order.
- **File-tuple detectors** read the N files sharing a contract (typically a pair). Right window for contract gaps. Examples: `obligation_violation`, cross-file string drift, schema/ABI mismatch. `obligations.py` already groups by file pair; this becomes the pattern for all contract-gap detectors.

Detectors that need broader context than their declared window — for instance, a contract detector that wants to confirm a third file is unaffected — declare it explicitly via the Evidence schema rather than reaching for ambient access. Triage retains global cross-file capability as a safety net.

### The Finding schema (A)

One dataclass replaces the ad-hoc per-detector output structures.

```python
@dataclass(frozen=True)
class Finding:
    # Identity
    id: str                          # stable hash of (detector, location, claim)
    detector: str                    # "dead_code", "stale_doc", "obligation_violation", ...
    gap_type: Literal["reachability", "description", "contract"]

    # Location
    path: str
    line_start: int | None
    line_end: int | None
    symbol: str | None               # function/class/param name when applicable

    # The claim
    contract_source: str             # "import statement", "function signature", "docstring", "shared string literal"
    contract_claim: str              # what the code/doc/contract states
    observed_behavior: str           # what actually happens

    # Evidence (typed; gathered before triage)
    evidence: list[Evidence]

    # Triage outcome (filled by Triage stage)
    verdict: Literal["confirmed", "dismissed", "uncertain"] | None
    confidence: float | None         # [0, 1]
    triage_reasoning: str | None     # the LLM's reasoning trace — load-bearing for C
    suggested_fix: str | None
    severity: Literal["error", "warning", "info"] | None

@dataclass(frozen=True)
class Evidence:
    kind: Literal["ast_fact", "cross_file_reference", "shadow_doc_claim",
                  "scanner_metadata", "git_blame", "type_signature"]
    weight_hint: float               # detector's prior on this evidence's value
    payload: dict                    # kind-specific structure
```

Detectors emit Findings with empty `verdict`/`confidence`/`reasoning`. Triage fills those fields. This is the single contract the rest of the system negotiates against.

### The Triage stage (B)

One LLM-driven stage replaces the six+ scattered verification gates. Inputs: a batch of [self-sufficient claims](../concepts/self-sufficient-claims.md) — Findings whose Evidence has been mechanically assembled to be sufficient for one-shot reasoning. Outputs: each Finding with verdict, confidence, reasoning, and suggested fix.

The Triage prompt is the single largest optimization target in the system. It encodes the three-gap rubric and instructs the model to weigh evidence kinds against the three TP predicates (reality, significance, actionability). The reasoning trace is captured verbatim — this is the "rich trace" gepa-style optimization needs in v2.

The rubric explicitly distinguishes hard-coded-literal classes per [string-contract taxonomy](../concepts/string-contract-taxonomy.md): named project obligations get confirmed (with a "use the existing constant" suggested fix); unnamed project obligations get confirmed (with an "extract a shared constant" suggested fix); ecosystem conventions (HTTP codes, file modes, RFC-defined strings) get dismissed with reasoning; ambiguous magic-constant duplications get examined case-by-case; coincidental duplications get dismissed as coincidence. This is the LLM filter the current `obligations.py` lacks; routing all literal-based findings through Triage is what makes the rubric enforceable.

When a claim arrives with the `insufficient_evidence` flag set (the Claim Builder couldn't fill required Evidence kinds), Triage escalates to exploration mode for that single claim — the LLM gets read/grep tool access and decides with retrieval. Cost stays bounded because the escalation rate is itself a tracked metric.

### Claim Builder

Between detector and Triage there is one mechanical pass — the [Claim Builder](../concepts/self-sufficient-claims.md) — that assembles each Finding into a self-sufficient claim: the hypothesis, mechanically-gathered case-FOR evidence, mechanically-gathered case-AGAINST evidence, positional context (without semantic interpretation), and the relevant compressed-code substrate (shadow docs at file / directory / root scope as the gap-type warrants). Triage receives a batch of these claims and decides each in one LLM call, no exploration needed by default.

Two sources feed the Claim Builder:

- **Propose-time evidence** — whatever the detector consulted to generate the hypothesis (a project-graph detector cites the cross-file reference list it inspected; a file-pair detector cites both file contents). Recording it makes the LLM's proposal auditable.
- **Builder-time evidence** — added by the Claim Builder pass: cross-file references from FactsDB, shadow doc content at appropriate scope, AGAINST-direction patterns (base class hierarchy for reachability, surrounding-code positional context for string contracts), and (in v2) OSS scanner output. This is where the current per-detector verification logic gets centralized. `_verify_debris_findings_async` (`src/osoji/audit.py:262-399`) and the five+ analyzer-specific verify methods all collapse into the Claim Builder + one Triage call per batch.

The Claim Builder's evidence schema is a **configuration object**, not a hardcoded class — a list of evidence-kind-builders to invoke per claim. This keeps the schema mutable so v2 can apply gepa-style ablation: a Claim Builder mutation that drops an Evidence kind shouldn't hurt verdict accuracy if the kind was non-load-bearing.

The Claim Builder's evidence schema is **bootstrapped from observation**, not stipulated. Step 3a in the [order of operations](#order-of-operations) below runs Triage in exploration mode against a representative test set, mines the LLM's tool-call traces for the Evidence kinds it consults, then mechanizes those kinds. Validate by ablation: rerun in claim-only mode and confirm verdicts match. This is the answer to "what evidence is sufficient?" — we measure rather than guess.

When the Claim Builder cannot fill a required Evidence kind, it sets the `insufficient_evidence` flag on the claim and Triage escalates that single claim to exploration mode (see [Triage stage above](#the-triage-stage-b)).

### Tree-sitter substrate (E in earlier discussion)

`src/osoji/plugins/python.py` and `src/osoji/plugins/typescript.py` are replaced by tree-sitter queries (`.scm` files) under `src/osoji/queries/<lang>/`. Each query produces the same outputs the current plugins produce: symbols, facts, AST kinds. The migration is port-not-redesign — outputs match existing snapshots — so the rest of the pipeline is unaffected.

Order: Python first (eat our own dogfood), TypeScript second, then onboard one additional language (likely Go) to validate that the abstraction is real.

### Sweep → fixture corpus (C-data)

The sweep skill (`src/osoji/skills/osoji-sweep.md`) gains a final phase that, in addition to filing GitHub issues, writes structured fixture stubs to `tests/fixtures/prompt_regression/<category>/case_NNN_<slug>/`. Each FP becomes:

- `expected.json` — the correct verdict, with reasoning
- A snapshot of the relevant source files
- A snapshot of relevant facts/symbols/shadow docs

The user (or Claude in a follow-up session) reviews the auto-generated fixture and either accepts it (committing to the corpus) or rejects it (adjusting the sweep classification first). This converts the sweep workflow's existing output into corpus growth.

The prompt-regression harness gets a new mode: `--evaluate` runs all fixtures and reports per-detector and overall TP/FP rates. This is the metric.

## Epistemological note

The "solid foundation" this rebuild aims for is layered, and being honest about which layer is which is part of what makes it solid. Four layers, with different revisability and different evidence requirements:

| Layer | Examples in this spec | Revisable how |
|---|---|---|
| **Stipulated** | The TP-predicate definition (reality + significance + actionability) | Definitional choice. Defensible because it operationalizes "matters." Not derived from anything. Revisable only by re-defining what counts as a finding. |
| **Taxonomic** | Three-gap theory; string-contract five-class rubric; Finding's `gap_type` and Evidence `kind` enums | Falsifiable engineering claims. Each closed-set taxonomy carries an `other`/`uncategorized` outlet. Revisable when the metrics below show the taxonomy is failing. |
| **Engineering** | Claim Builder over exploration-mode; per-file/project-graph/file-tuple dispatch; shadow docs as primary compressed-code substrate; gepa as v2 optimizer target | Design choices supported by current evidence. Reversible at the [Finding schema](#the-finding-schema-a) boundary. Not provably optimal. Revisable when a measurement disagrees. |
| **Measured** | Per-detector TP/FP rates; CE-gap and ME-overlap rates per taxonomy; escalation rate from Claim Builder; verdict-disagreement between claim-mode and exploration-mode in bootstrap | What we actually know. Outputs of the regression evaluator and the sweep-fixture corpus. Drives revisions to the layers above. |

Two falsifiability metrics per closed-set taxonomy, applied differently by use:

- **CE-gap rate** (proportion of items classified `other`/`uncategorized`) for taxonomies in *generative* use (frame what we're looking for). Rising rate signals a missing category.
- **ME-overlap rate** (proportion of items legitimately fitting multiple categories that route to non-overlapping analysis) for taxonomies in *analytical* use (route to different pipelines). Structural overlap signals the dispatch boundary is wrong.

Three-gap theory serves both uses, so it carries both metrics. The string-contract taxonomy is descriptive only (Triage rubric vocabulary), so only CE-gap matters. Detector context windows is dispatch only, so only ME-overlap matters.

This framing is itself revisable — but the discipline behind it (no closed-set taxonomy without an `other` outlet and a metric on its adequacy) is the meta-principle the v1 architecture should not silently abandon.

## Repository layout

Two repos, one organization:

**`../osoji-wiki/`** (new) — packaged as `osoji-wiki`. Original plan-text said `osoji-wiki-mcp`; the bootstrap session resolved on the shorter `osoji-wiki` name. See [specs/0002-wiki-bootstrap.md](0002-wiki-bootstrap.md).

```
osoji-wiki/
├── pyproject.toml
├── src/osoji_wiki/
│   ├── server.py            # MCP server entry
│   ├── store.py             # filesystem-backed page store
│   ├── concurrency.py       # CAS, atomic rename, per-file locks
│   └── frontmatter.py       # metadata management
├── skills/
│   ├── brief.md             # Claude Code skill (slash command)
│   └── debrief.md
└── tests/
```

Tools: `wiki_read`, `wiki_edit`, `wiki_write`, `wiki_delete`, `wiki_move`, `wiki_list`. CAS via SHA-256 of body (frontmatter excluded from hash). Atomic writes via tempfile+rename. Per-file locks during the verify→write critical section.

**`./osoji/`** (existing):

- New: `wiki/` directory at repo root, with `SCHEMA.md`, `index.md`, `log.md`, and subdirs `concepts/`, `specs/`, `decisions/`, `detectors/`, `sources/`. (Bootstrapped in [specs/0002-wiki-bootstrap.md](0002-wiki-bootstrap.md).)
- New: `src/osoji/findings.py` — the Finding and Evidence dataclasses.
- New: `src/osoji/triage.py` — unified Triage stage.
- New: `src/osoji/evidence.py` — evidence-gathering pass.
- New: `src/osoji/queries/` — tree-sitter query files.
- Refactor: `src/osoji/audit.py` — phase orchestration collapses; per-phase verify methods removed.
- Refactor: each detector module — produces Findings, no internal verification.
- Refactor: `src/osoji/plugins/` — replaced by tree-sitter loader + queries.
- Reuse: `tools.py` (LLM tool schemas, central registry — survives), `facts.py` (`FactsDB.cross_file_references` is exactly what evidence-gathering needs), `symbols.py`, `walker.py`, `hasher.py`, `rate_limiter.py`, `llm/`, `safety/`.
- Update: `tests/test_prompt_regression.py` gains `--evaluate` mode; existing 8 fixtures port forward.
- Update: `src/osoji/skills/osoji-sweep.md` — adds fixture-emitting phase.
- Update: `CLAUDE.md` — short section pointing at the wiki and brief/debrief workflow.

## Order of operations

Architecture-first. Tree-sitter migration is a port, not a redesign — it's safer to do it once the Finding schema and Triage are settled.

1. **Bootstrap session.** Create `osoji-wiki` repo. Implement MCP server (read/edit/write/delete/move/list with CAS). Bootstrap `wiki/` in osoji repo. Ingest this plan, the three-gap theory, the language-choice analysis, and the v1-scope decision as the first wiki entries. Wire `/brief` and `/debrief` skills. **Status: completed; see [specs/0002-wiki-bootstrap.md](0002-wiki-bootstrap.md).**
2. **Finding schema + evidence model + detector context taxonomy.** Implement `findings.py` and `evidence.py`. Classify every existing detector into per-file / project-graph / file-tuple. No behavior change yet — existing detectors still emit their old shapes; an adapter converts to Findings. Ship this as a single PR; CI green.
3. **Unified Triage stage (with both modes).** Implement `triage.py` supporting both exploration mode (LLM has tool access; used for bootstrap and escalation) and claim mode (LLM receives self-sufficient claims; default path). Migrate Phase 3 debris verification to claim mode with an initial-guess Claim Builder schema. Verify behavior is preserved on existing `prompt_regression` fixtures. PR.
4. **Exploration-mode bootstrap and Claim Builder ablation.** Run Triage in exploration mode against a curated test set (existing `prompt_regression` fixtures plus a representative sample from the audit-osoji-on-osoji corpus). Log every tool call. Mine successful traces for the Evidence kinds the LLM consults. Mechanize those kinds in the Claim Builder. Ablate by rerunning in claim mode and measuring verdict-disagreement against the exploration baseline. Iterate until disagreement is below threshold. The output is the v1 Claim Builder schema, empirically derived. PR.
5. **Migrate detectors to their declared context windows.** This is where the FP-class the user has been fighting actually gets fixed. Reachability detectors (`deadcode`, `deadparam`, `plumbing`, `junk_orphan`, `junk_deps`) start consuming FactsDB at *propose* time, not just at filter/verify time — meaning their LLM proposal step sees cross-file references upfront. Contract detectors (`obligations` and any cross-file `latent_bug` cases) propose against file-tuple input. Per-file detectors (most `doc_analysis` paths, `stale_comment`, in-file `latent_bug`) keep their per-file shadow input unchanged. Per-analyzer verify methods deleted; the Claim Builder + Triage take over. PR per analyzer or grouped, owner's choice.
6. **Tree-sitter migration.** Python first; query outputs cross-validated against existing plugin snapshots. Then TypeScript. Then Go as the third language to prove the abstraction. PR per language.
7. **Sweep → fixture corpus.** Add fixture-emitting phase to sweep skill. Add `--evaluate` mode to prompt-regression. Add CE-gap and ME-overlap rate tracking per taxonomy. Add Claim Builder escalation-rate tracking. Run sweep on osoji itself to seed the corpus.
8. **Three-gap docs in wiki, dogfood evaluation.** Final concept pages. Run `--evaluate` and publish baseline TP/FP rates per detector along with taxonomy adequacy and escalation rates.

Each step ships as a PR through the existing branch-protection workflow. CI must stay green throughout.

## Language

Python. See [decisions/0002-language-choice.md](../decisions/0002-language-choice.md) for the full reasoning. Short version: the hot path is the LLM call, not the AST work; py-tree-sitter is fast enough; the Finding schema will evolve and Python's type-as-aspiration makes that cheap; the OSS scanner ecosystem we want to absorb in v2 is largely Python-native. If/when AST/facts becomes the bottleneck, extract to a Rust sidecar emitting JSON across the Finding schema boundary that already exists. Don't speculate now.

## Reuse map (existing assets that survive)

| Asset | Role in v1 |
|---|---|
| `tools.py` | Tool schema registry — survives. New schemas added for Triage; old per-analyzer verify schemas deleted. |
| `facts.py` (FactsDB) | Evidence-gathering backend. `cross_file_references` is the canonical example. |
| `symbols.py` | Evidence kind `ast_fact` payload source. |
| `tests/test_prompt_regression.py` | Becomes the evaluator. `tests/stat_utils.py` (binomial test) survives as-is. |
| `tests/fixtures/prompt_regression/` | Seed corpus. Port `expected.json` to include verdicts in the new Finding shape. |
| `walker.py`, `hasher.py`, `rate_limiter.py`, `llm/`, `safety/`, `config.py` | Survive untouched. |
| `osoji-sweep` skill | Survives, gains fixture-emitting phase. |
| `audit.py` orchestration shape | Survives; phases become coherent (detector → evidence → triage) rather than each-phase-its-own-verify. |
| `shadow.py` | Survives; shadow generation mechanism is unchanged but **repositioned** as the input to *per-file* detectors only (description gaps), not as the universal substrate from which all findings are extracted. Shadow content also serves as triage-time Evidence. |

## Verification

A v1 release ships when all of the following hold:

1. **Existing prompt-regression fixtures all pass** at their established baselines, run through the new architecture. (Behavior preservation.)
2. **New `--evaluate` mode** reports per-detector TP/FP rates on the seeded corpus. Initial corpus comes from one full sweep of osoji on osoji.
3. **Falsifiability metrics tracked**: CE-gap rate per taxonomy in generative use (notably `gap_type=uncategorized` rate, `string-class=other` rate); ME-overlap rate per taxonomy in analytical use; Claim Builder escalation rate. Each baselined.
4. **`osoji audit --full .` on the osoji repo** runs end-to-end through the unified architecture, finishes within 10% of current wall-clock time, and produces Findings with verdicts/confidence/reasoning populated. Audit cost grows roughly linearly with finding count (claim-mode dominant; escalation as a small surcharge).
5. **Claim Builder bootstrap converged**: verdict-disagreement between claim-mode and exploration-mode below threshold (e.g., 5%) on the bootstrap test set. The empirically-derived Evidence schema is checked in.
6. **Tree-sitter Python and TypeScript queries** produce symbol/fact outputs that match the deprecated plugins on a snapshot test. One additional language (Go) onboarded as a smoke test of the abstraction.
7. **Wiki coverage**: every concept and decision in this plan exists as a wiki page, with cross-references and an updated index.
8. **CLAUDE.md updated** to point at the wiki, the brief/debrief workflow, and the closed-set-taxonomy-must-have-`other`-outlet meta-principle.
9. **Detector context audit**: every detector documents its declared context-window class (per-file / project-graph / file-tuple) and does not read beyond it at propose time. Recorded in `wiki/detectors/<name>.md` for each detector.

## Out of scope for v1 (becomes v2/v3)

- gepa-style reflective optimizer that mutates the Triage prompt — needs the corpus to grow first.
- OSS scanner adapters (semgrep, ruff, bandit, gosec, eslint) — once the Finding schema is proven on osoji's own detectors.
- VS Code extension — needs a stable Finding schema to render against.
- Rust sidecar for AST/facts — only if measurement justifies it.
- Multi-user wiki MCP semantics — single-human-multiple-agents is enough for v1.

## Open questions deferred to session-level decisions

- Exact wire format between detectors and the Claim Builder pass (in-process call vs. typed bus). Resolve in step 2.
- Whether sweep's auto-generated fixtures land in a holding directory pending review, or directly in `tests/fixtures/`. Resolve when implementing step 7.
- Bootstrap test set composition for step 4: osoji-on-osoji only, or include sweeps from diverse projects? Probably a mix; resolve when the first bootstrap runs.
- Whether the Claim Builder schema is serialized as Python config (a list of evidence-kind callables) or as a separate config format (YAML/JSON). The latter is friendlier to gepa-style mutation in v2; the former is simpler in v1. Resolve in step 3.
- Per-Evidence-kind weighting: keep the `weight_hint` field, or remove it and let the LLM weight implicitly? Defer until the bootstrap measures whether weights move verdicts.
- ~~Whether the brief/debrief sub-agents use the MCP server's prompt resources or are reimplemented in skill markdown.~~ **Resolved in [specs/0002-wiki-bootstrap.md](0002-wiki-bootstrap.md): skills only, no MCP prompts in v1.**
