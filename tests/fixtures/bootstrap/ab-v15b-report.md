# V1-5b A/B report: plumbing + orphan + deps + cicd, legacy pipeline vs unified Triage

**Ticket:** osojicode/work#29 (scope +junk_cicd per 2026-07-04 comment) · **Branch:** `v1-5b-junk-project-graph` · **Date:** 2026-07-04

## Design

Same-tree pipeline A/B per decision 0016: one worktree pinned at `origin/main` @ `a906f3f`,
one copy of `.osoji` artifacts (restored from a pristine snapshot between sides), varying only
pipeline code via `PYTHONPATH`:

```
PYTHONUTF8=1 PYTHONPATH=<side>/src python -c "from osoji.cli import main; main()" \
    audit . --dead-plumbing --orphaned-files --dead-deps --dead-cicd \
    --exclude shadow,doc-analysis,debris --no-fix --format json
```

Provider: anthropic (builtin default), model tier `medium` (claude-sonnet-4-6) both sides.

## Headline

| | main (legacy per-analyzer verify) | branch (candidate adapters + unified Triage) |
|---|---|---|
| unactuated_config findings | 2 | 0 |
| orphaned_file / dead_dependency / dead_cicd | 0 / 0 / 0 | 0 / 0 / 0 |
| **adjudicated false positives** | **2** | **0** |
| adjudicated true positives | 0 | 0 |
| API tokens (total run) | 142,842 | 58,579 (first run) / 117,154 (post-fix rerun) |

Both main-side findings are corpus-confirmed FPs: `Finding.confidence` and
`Finding.evidence_fingerprint` (`src/osoji/findings.py:96,101`) are dataclass fields the
legacy extract stage misread as config obligations — both are demonstrably actuated
(Triage populates `confidence`; the verdict cache keys on `evidence_fingerprint`; both
test-pinned). `unactuated_config-case_001-confidence` exists in the bootstrap corpus with
an adjudicated `dismissed`. The legacy verify confirmed both against its own quoted evidence.

Token note: side-B totals vary across runs (58,579 → 117,154; −59% to −18% vs main). The
variable component is the orphan analyzer's LLM entry-point stage, which is unchanged by
this migration. Reported as a range rather than a point estimate.

## Corpus re-check (7 slugs, claim mode, branch pipeline)

| Category | Result |
|---|---|
| dead_parameter (4 slugs incl. both confirmed + both dismissed labels) | 4/4 agree, both runs |
| unactuated_config (3 slugs) | pre-fix 2/3 → post-fix **3/3** |

The pre-fix miss was `unactuated_config-case_002-Request` (a field in a vendored Debug
Adapter Protocol reference JSON, adjudicated dismissed, agreeing before this branch): the new
actuation clause instructed the model that nothing short of enforcement refutes the gap,
overriding its correct vendored-material judgment. Fixed by a balancing scoping principle in
the same rubric section (commit `ecafcea`): *an unactuated-config gap exists only for
obligations the project itself declares*. This principle is **gate-discovered, not
inherited** — the legacy verify prompt did not contain it (recorded in the prompt-principle
inheritance audit).

## Fixture baselines

- plumbing_001 (tool_schema), plumbing_002 (doc_json_reference): PASS
- dead_params_002 (high_fanout): PASS
- dead_params_001 (backward_compat): 9/10 in two pytest runs under concurrent API load;
  10/10 + 20/20 in sequential verdict-detail diagnostics and 10/10 in an instrumented pytest
  rerun (branch aggregate 58/60 vs main 40/40 incl. the 30-trial baseline). The two failures
  never reproduced under instrumentation; no verdict-level detail was captured for them
  (the trial bool conflates infrastructure failure with wrong verdicts — noted for V1-7).
  Disclosed rather than hidden; if the rate persists post-merge, re-establish the baseline or
  make the harness load-tolerant.

## Out-of-distribution run (mcp-debugger, TS-dominant, day-zero artifacts reused)

- plumbing: 2 obligations proposed (1 in rerun — extract-stage variance) → 0 confirmed
- deps: 33 dependencies, 33/33 import names resolved, 3 zero-import → all pre-filtered as
  build tooling → 0 claims
- cicd: 17 elements, 8 with missing path references triaged → 0 confirmed.
  **Independent re-derivation adjudication**: ~56 path references checked across 7 workflows,
  2 Dockerfiles, compose, and npm scripts; every miss is generated-at-build-time or dynamic;
  **"0 confirmed" holds, no suppressed TP**. (Two genuinely dead npm scripts exist —
  `test:failures`/`test:summary` → moved helper files — but no workflow invokes them; they are
  out of dead-cicd scope and suggest a future dead-npm-script detector.)
- orphan: 438-file import graph, 291 entry points, BFS 0 disconnected → 0 candidates
- Tokens: 139,686 (first OOD run, all four analyzers)

## Deliberate deltas (documented, accepted)

- The four analyzers' verify prompts and tool schemas are deleted; their decision principles
  are inherited into the unified rubric's reachability section (3 clauses: plumbing
  actuation, orphan file-level conventions, cicd holistic missing-path weighting) plus the
  gate-discovered vendored-material scoping principle.
- deps `total_candidates` now counts genuine candidates examined rather than dead deps found.
