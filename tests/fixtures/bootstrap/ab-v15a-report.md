# V1-5a A/B report: deadcode + deadparam, legacy pipeline vs unified Triage

**Ticket:** osojicode/work#28 · **Branch:** `v1-5a-reachability-cutover` · **Date:** 2026-07-03

## Design

Both sides audited the **identical tree and `.osoji` artifacts** (a worktree pinned at
`origin/main` @ `6a4089d`, artifacts copied from the primary clone), varying only the
pipeline code via `PYTHONPATH`:

```
PYTHONUTF8=1 PYTHONPATH=<side>/src python -c "from osoji.cli import main; main()" \
    audit . --dead-code --dead-params --exclude shadow,doc-analysis,debris --no-fix --format json
```

Provider: anthropic, model tier `medium` (claude-sonnet-4-6) on both sides. This isolates
the migration's effect: same candidates, same facts/symbols staleness, different
verification.

## Headline

| | main (legacy per-detector verify) | branch (Claim Builder + unified Triage) |
|---|---|---|
| dead_symbol findings | 13 (all AST-proven, no LLM review) | 2 |
| dead_parameter findings | 6 | 2 |
| **adjudicated false positives** | **15** | **0** |
| adjudicated true positives | 4 | 4 |
| scorecard junk lines | 134 | 39 |
| API tokens (total run) | 799,039 | 705,743 (−12%) |

Every one of main's 15 false positives is dropped; every true positive is kept. The
branch triages *more* candidates through the LLM (AST demotions) yet spends fewer tokens,
because bounded claims replace full-file prompts.

## Adjudication of the 15 removed findings (all FPs on main)

| Finding | Why it was an FP | What caught it |
|---|---|---|
| `RateLimitedProvider.get_rate_limit_summary` | invoked via getattr string-dispatch (`llm/logging.py`) | AST demotion guard + `in_string_literal` flag + dispatch rubric (the `dead_symbol-001` ablation residual) |
| `DirectProvider.set_interaction_log_path` | getattr string-dispatch (`llm/runtime.py:22-24`) | same |
| `TokenCounter.count_text_async` | called at `stats.py:126,133`; AST facts stale | claim sweep found the call sites |
| `EvidenceBuilder`, `BUILDERS` (evidence.py) | subclassed/imported by `evidence_builders.py`; facts sidecar missing (file postdates last regen) | claim sweep found the import + subclass sites |
| 6 × `scripts/triage_bootstrap.py` symbols | used within the script, which runs as `__main__`; scripts have no importers so the AST path confirmed blind | same-file sweep outside the flagged region |
| 4 × `findings_adapter.*.root` params | `finding_from_debris(..., root=config.root_path)` at `claim_builder.py:253`; others exercised by tests | function-needle call-site evidence |

## The one regression the A/B caught (fixed before merge)

In the first side-B run the LLM **cross-wired batch indices** between two sibling claims
(`Triage.__init__.executor` vs `.rate_limiter` — same function, near-identical claims):
`executor`'s reasoning landed on `rate_limiter`, producing one wrong confirm and one lost
TP. Fixed with a symbol-echo field on `submit_triage_verdicts` + a completeness-validator
cross-check (mismatch → validation retry). The re-run confirms `executor` correctly with
its own reasoning.

## Deliberate deltas (documented, accepted)

- Some `[AST]`-prefixed findings become `llm_inferred` (demotions cost tokens; that is
  the point — string-keyed reachability is invisible to the AST graph).
- `dead_parameter` findings anchor on the signature line; `gated_line_ranges` died with
  the per-detector verify tool (scorecard `junk_lines` shrinks accordingly).
- `.osoji` staleness affected both sides equally (facts missing for V1-4-era files);
  the legacy AST path confirmed blind where the claim sweep recovered.

## Artifacts

Raw audit JSONs (side A, side B initial + final) retained locally; bootstrap corpus
re-check traces committed under `traces/claim-v15a/`.

## Addendum: first out-of-distribution run (mcp-debugger, 2026-07-04)

Day-zero run on `osojicode/mcp-debugger` (public, TypeScript-dominant: 341 `.ts` + 26
`.py`, no prior `.osoji`), claude-code provider: shadow generation for 489 source files,
then `--dead-code --dead-params` through the unified pipeline.

**It caught a corpus-honesty bug invisible in-distribution.** `BuildContext.scan_files`
globbed the working tree raw: mcp-debugger's checked-out `dist/`, `dist-tarball/`,
`coverage/` and friends made 12,219 glob entries vs 822 repo files, the
`_MAX_SCAN_FILES=5000` cap truncated in glob order, and the flagged file itself fell
outside the corpus — so a "zero matches" sweep mechanically confirmed
`SWAP_SCRIPT_PATH`, a constant its own file uses four times. Fixed (commit `75f8a2a`):
walker-based corpus (git-tracked/ignore-filtered), flagged file always swept,
truncation flagged in `scan_scope`, rendered as a caution, and vetoing mechanical
confirms. The raw glob had a second failure direction the fix also closes: stale build
artifacts vouching for deleted source symbols.

**Corrected result: 50 candidates proposed (12 AST-demoted + 12 grep + 26 params),
0 confirmed.** Hand adjudication of a dismissal sample agrees: the zero-ref symbols are
example-script locals, same-file subclass anchors (`LanguageRuntimeNotFoundError` →
`PythonNotFoundError`), injectable same-file defaults (`listTaggedJvms`), and MCP tool
parameters passed dynamically from protocol dispatch (`args.includeInternals ?? false`)
— a well-kept repo, correctly reported as such. ~22.5K output tokens for the audit.
