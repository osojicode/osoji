# Wiki edit log

Append-only changelog of wiki edits. Format: `YYYY-MM-DD <op> <path> — <one-line summary>`.

`<op>` is one of `write` (new page), `edit` (content change), `move` (rename), `delete` (removal), `status` (frontmatter status bump only).

---

2026-04-29 write SCHEMA.md — bootstrap: define wiki page format and lifecycle
2026-04-29 write index.md — bootstrap: create top-level index
2026-04-29 write log.md — bootstrap: create changelog
2026-04-29 write specs/0001-v1-foundation.md — bootstrap: ingest the v1-foundation plan as the inaugural spec
2026-04-29 write specs/0002-wiki-bootstrap.md — bootstrap: record this session's plan
2026-04-29 write concepts/three-gap-theory.md — bootstrap: define reachability/description/contract gap taxonomy and minimum-context invariants
2026-04-29 write decisions/0002-language-choice.md — bootstrap: capture decision to stay on Python for v1 with a sidecar door left open
2026-04-29 edit concepts/three-gap-theory.md — add `uncategorized` outlet; refine description-gap minimum context to scope spectrum (file/directory/root); add CE-gap and ME-overlap falsifiability framing
2026-04-29 write concepts/string-contract-taxonomy.md — five-class Triage rubric (named obligation, unnamed obligation, ecosystem convention, magic-constant duplication, coincidence) plus `other` outlet; framed as descriptive Triage rubric, not detector logic
2026-04-29 write concepts/self-sufficient-claims.md — Claim Builder design: bootstrap from exploration traces, positional vs semantic division of labor, shadow-doc-primary substrate, escalation path, gepa-optimizable schema as v2 target
2026-04-29 edit specs/0001-v1-foundation.md — Claim Builder replaces ad-hoc evidence gathering; new step 4 (exploration-mode bootstrap and ablation); add Epistemological Note section with four-layer foundation (stipulated/taxonomic/engineering/measured); Verification gains escalation-rate, falsifiability-metrics, and bootstrap-convergence criteria
2026-04-29 edit index.md — add string-contract-taxonomy and self-sufficient-claims entries; update detector section reference (step 4 → 5)
2026-04-29 edit ../CLAUDE.md — add closed-set-taxonomies-need-`other` and mechanical-vs-LLM-boundary-decided-by-measurement to pipeline engineering principles
2026-04-29 write decisions/0003-plugin-packaging.md — record plugin packaging decision; supersedes manual install from spec 0002
2026-04-29 edit specs/0002-wiki-bootstrap.md — note install workflow superseded by decision 0003
2026-04-29 edit index.md — add decision 0003 entry
