# Exploration-tier A/B on the rails-failure cohort (osojicode/work#92)

**Question.** On the corpus cases the rails (evidence-bundle) triage gets wrong,
does replacing evidence assembly with bounded agentic retrieval — the model
explores the staged snapshot itself via read_file/grep/list_dir — change the
verdicts? This is the deciding experiment for the escalation-tier design
(osojicode/work#92) and the acceptance-set premise of referenced-artifact
resolution (osojicode/work#80).

## Design

| | rails baseline | rails control | exploration |
|---|---|---|---|
| run | `eval-20260723-ae5340c5` | `eval-20260724-rails92c` | `eval-20260724-explor92` |
| mode | claim (144-case batches) | claim (9-claim batch) | exploration (per-case loop) |
| repeats | 1 | 3 | 3 |
| tokens in/out | 357,553 / 46,937 (144 cases) | 71,970 / 8,751 | 716,490 / 36,539 |

- Cohort: the 9 cases the baseline got wrong — the panel-override
  stale_comment set (228/242/243/239, all expected `dismissed`, live pipeline
  confirms or wavers) plus every baseline `uncertain` (172/208/221/145/167).
- All three arms: identical rubric (prompt sha `807be646…` verified in each
  run_meta), model `claude-sonnet-4-6`, provider anthropic, evidence policy
  per case (`rebuild`).
- Exploration: same system prompt; the claim block is presented WITHOUT a
  pre-assembled evidence bundle; the model retrieves via read_file/grep/
  list_dir rooted at the case's staged snapshot, ≤8 turns, then
  `submit_triage_verdict`. Traces: `eval-20260724-explor92-traces.json`.
- Scoring: majority of 3 repeats. Same-prompt churn floor on this pipeline is
  ~13%, so single-repeat flips are noise, not signal. The rails control shares
  the exploration arm's 9-claim batch composition, isolating batch-context
  effects from the baseline's 144-case chunking.

## Per-case verdicts (expected → arm majorities)

| case | expected | baseline (1×) | rails control (3×) | exploration (3×) |
|---|---|---|---|---|
| stale_comment/228 agent-demo | dismissed | confirmed 0.85 | **confirmed 3/3** | **confirmed 3/3** (0.90–0.95) |
| stale_comment/242 cleanup-procs | dismissed | confirmed 0.87 | **confirmed 3/3** | **confirmed 3/3** (0.85–0.90) |
| stale_comment/243 jdi-bridge | dismissed | confirmed 0.82 | **confirmed 3/3** | **confirmed 2/3** (one dismissed 0.92) |
| stale_comment/239 type-guards | dismissed | uncertain 0.55 | uncertain 2/3 | **confirmed 3/3 (0.97)** — worse |
| doc_incorrect/172 testing-arch | dismissed | uncertain 0.5 | uncertain 2/3 | ✔ **dismissed 3/3** (0.95–0.97) |
| doc_incorrect/208 testing-arch-v2 | dismissed | uncertain 0.75 | ✔ dismissed 3/3 | ✔ dismissed 3/3 |
| stale_comment/167 line-ref | dismissed | uncertain 0.5 | ✔ dismissed 3/3 | **confirmed 2/3** — degraded |
| obligation/145 | dismissed | uncertain 0.5 | uncertain 2/3 | uncertain 3/3 (turn-limit, conf 0.0) |
| latent_bug/221 (gray) | confirmed | uncertain 0.5 | uncertain 3/3 | uncertain 3/3 (turn-limit, conf 0.0) |

**Non-gray score (8 cases): baseline 0/8 · rails control 2/8 (167, 208) ·
exploration 2/8 (172, 208).** Exploration and rails-control fix *different*
cases and exploration actively degrades one (167).

## Cost

| arm | $/decide (episode) | notes |
|---|---|---|
| rails (batched) | ~$0.013 | prompt amortized over the chunk |
| exploration | ~$0.100 avg, $0.25+ worst | 7.7× avg; turn-limit episodes (145/221) burn 20–100k input tokens to conclude `uncertain` conf 0.0 |

Whole experiment: ≈$3.1 (smoke + control + exploration).

## Trace mechanism classification (the work#80 acceptance set)

Every acceptance-set episode **did read the artifact the comment cites**:

- **228**: single `read_file examples/agent_demo.py` → confirmed. The full
  comment text (a disjunction) was in context; the model still reads half of
  it and sides with the finding against the panel adjudication.
- **242**: read `scripts/cleanup-test-processes.js` (the flagged file itself)
  → confirmed. The drift claim restates the comment; full file access didn't
  surface that.
- **243**: read `compile-jdi-bridge.js`, grepped `execFileSync` → 2/3
  confirmed. The single dismissal (0.92) reproduces the panel's mechanical
  `execFileSync` stdout argument — reachable but not stable (churn-level).
- **239**: multi-hop — grep `serializeAdapterCommand`, read
  `src/utils/type-guards.ts` AND its test, 5–6 turns — a strict superset of
  what deterministic referenced-artifact fetch (work#80) would supply. Result:
  confirmed 0.97 × 3, *more* confidently wrong than the baseline's uncertain.

Conclusion: **evidence access is not the binding constraint for this set.**
The cluster survived two rubric formulations (ab-descfam-report.md) and now
survives full evidence access; the disagreement is in adjudication itself
(model-vs-panel), a third axis distinct from rubric and evidence.

The two genuine evidence-access behaviors observed:

- **172 (fixed)**: grep the doc's flag name → read `tests/vitest.setup.ts` +
  the doc → dismissed ≥0.95, 3/3, in 3–4 turns. The rails bundle lacked the
  implementing file; a *deterministic* cited-artifact fetch would supply it.
  This is the one case matching work#80's mechanism.
- **167 (degraded)**: self-directed retrieval flailed (repeated broad greps,
  empty results) and confirmed 2/3 where the curated bundle dismissed 3/3.
  Uncurated retrieval can be strictly worse than a good bundle.

## Decision inputs

1. **work#92 (escalation tier)**: not justified by this cohort. At 7.7× cost,
   exploration nets zero aggregate accuracy gain (2/8 vs 2/8), degrades one
   case, and its two hardest cases exhaust the turn budget at conf 0.0.
   The `would_escalate`/insufficiency routing premise is also untriggered:
   every cohort claim had a full evidence bundle (`insufficient_evidence:
   false` across all 27 records).
2. **work#80 (referenced-artifact resolution)**: the 4-case acceptance set
   (228/242/243/239) is measured unreachable by evidence acquisition — those
   cases received the cited artifacts and got worse or stayed wrong. Expected
   yield of deterministic fetch on this cohort is case_172-shaped gaps
   (bundle missing the implementing file for a doc claim), not the
   stale_comment override cluster. The ticket's acceptance criterion needs
   re-founding.
3. **Adjudication-bound cluster**: 228/242/239 (and 243 marginally) now have
   a two-axis null result (rubric × evidence). Remaining hypotheses: the
   panel adjudications encode judgment the production model does not share at
   any evidence level, or the expected verdicts themselves warrant
   re-examination. Either way this is an adjudication/consistency question,
   not a pipeline-mechanism question.
4. **Trace mining** (the standing bootstrap method): the 172 traces are a
   worked example of a new mechanical evidence kind — "resolve a doc-cited
   config/flag name to its implementing file and include that file" — directly
   implementable in the description-family builder.
