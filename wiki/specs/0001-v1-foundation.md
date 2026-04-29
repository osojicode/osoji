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

- **Per-file detectors** read one source file (and that file's shadow doc). Right window for description gaps. Examples: `stale_comment`, `misleading_claim`, `latent_bug` when the bug is local, doc-accuracy errors. Shadow generation continues to feed these — shadow docs are repositioned as *the input to per-file detectors*, not as the universal substrate from which all findings are extracted.
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

One LLM-driven stage replaces the six+ scattered verification gates. Inputs: a batch of Findings with their gathered Evidence, plus shadow doc / facts context. Outputs: each Finding with verdict, confidence, reasoning, and suggested fix.

The Triage prompt is the single largest optimization target in the system. It encodes the three-gap rubric and instructs the model to weigh evidence kinds against the three TP predicates (reality, significance, actionability). The reasoning trace is captured verbatim — this is the "rich trace" gepa-style optimization needs in v2.

### Evidence gathering

Evidence appears at two distinct points and the Finding schema records both:

- **Propose-time evidence** is whatever the detector consulted to *generate* the hypothesis (e.g., a project-graph detector cites the cross-file reference list it inspected; a file-pair detector cites both file contents). This is required input to the detector by its context-window class. Recording it makes the LLM's proposal auditable — Triage can see what the proposer saw.
- **Triage-time evidence** is gathered after proposal by a single evidence-gathering pass that uses FactsDB, shadow docs, symbols, and (in v2) OSS scanner output to attach additional supporting data. This is where current per-detector verification logic gets centralized. `_verify_debris_findings_async` (`src/osoji/audit.py:262-399`) and the five+ analyzer-specific verify methods all collapse into one gathering pass + one Triage call.

Detectors don't gather their own *triage* evidence; they produce hypotheses with their propose-time context attached, the gathering pass adds the rest, Triage decides.

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
3. **Unified Triage stage.** Implement `triage.py`. Migrate Phase 3 debris verification to use it. Verify behavior is preserved on existing `prompt_regression` fixtures. PR.
4. **Migrate detectors to their declared context windows.** This is where the FP-class the user has been fighting actually gets fixed. Reachability detectors (`deadcode`, `deadparam`, `plumbing`, `junk_orphan`, `junk_deps`) start consuming FactsDB at *propose* time, not just at filter/verify time — meaning their LLM proposal step sees cross-file references upfront. Contract detectors (`obligations` and any cross-file `latent_bug` cases) propose against file-tuple input. Per-file detectors (most `doc_analysis` paths, `stale_comment`, in-file `latent_bug`) keep their per-file shadow input unchanged. Per-analyzer verify methods deleted; Triage takes over. PR per analyzer or grouped, owner's choice.
5. **Tree-sitter migration.** Python first; query outputs cross-validated against existing plugin snapshots. Then TypeScript. Then Go as the third language to prove the abstraction. PR per language.
6. **Sweep → fixture corpus.** Add fixture-emitting phase to sweep skill. Add `--evaluate` mode to prompt-regression. Run sweep on osoji itself to seed the corpus.
7. **Three-gap docs in wiki, dogfood evaluation.** Final concept pages. Run `--evaluate` and publish baseline TP/FP rates per detector.

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
3. **`osoji audit --full .` on the osoji repo** runs end-to-end through the unified architecture, finishes within 10% of current wall-clock time, and produces Findings with verdicts/confidence/reasoning populated.
4. **Tree-sitter Python and TypeScript queries** produce symbol/fact outputs that match the deprecated plugins on a snapshot test. One additional language (Go) onboarded as a smoke test of the abstraction.
5. **Wiki coverage**: every concept and decision in this plan exists as a wiki page, with cross-references and an updated index.
6. **CLAUDE.md updated** to point at the wiki and brief/debrief workflow.
7. **Detector context audit**: every detector documents its declared context-window class (per-file / project-graph / file-tuple) and does not read beyond it at propose time. Recorded in `wiki/detectors/<name>.md` for each detector.

## Out of scope for v1 (becomes v2/v3)

- gepa-style reflective optimizer that mutates the Triage prompt — needs the corpus to grow first.
- OSS scanner adapters (semgrep, ruff, bandit, gosec, eslint) — once the Finding schema is proven on osoji's own detectors.
- VS Code extension — needs a stable Finding schema to render against.
- Rust sidecar for AST/facts — only if measurement justifies it.
- Multi-user wiki MCP semantics — single-human-multiple-agents is enough for v1.

## Open questions deferred to session-level decisions

- Exact wire format between detectors and the evidence-gathering pass (in-process call vs. typed bus). Resolve in step 2.
- Whether sweep's auto-generated fixtures land in a holding directory pending review, or directly in `tests/fixtures/`. Resolve when implementing step 6.
- ~~Whether the brief/debrief sub-agents use the MCP server's prompt resources or are reimplemented in skill markdown.~~ **Resolved in [specs/0002-wiki-bootstrap.md](0002-wiki-bootstrap.md): skills only, no MCP prompts in v1.**
