# Osoji wiki — index

The wiki captures design rationale, concepts, decisions, and detector notes that survive across agent sessions. See [`SCHEMA.md`](SCHEMA.md) for the page format.

Tooling: [`osoji-wiki`](https://github.com/osojicode/osoji-wiki) — MCP server with `wiki_*` tools and `/brief` `/debrief` skills.

## Specs

- [0001 — V1 Foundation: Unified Finding/Triage Architecture](specs/0001-v1-foundation.md) (status: draft) — the foundation rebuild plan; introduces three-gap theory, single Triage stage, tree-sitter substrate, fixture corpus.
- [0002 — Wiki Bootstrap](specs/0002-wiki-bootstrap.md) (status: accepted) — creation of this wiki and the `osoji-wiki` MCP server.

## Concepts

- [Three-gap theory](concepts/three-gap-theory.md) — the unifying frame for every osoji finding: reachability gaps, description gaps, contract gaps, with minimum-context invariants and a falsifiability framing.
- [String-contract taxonomy](concepts/string-contract-taxonomy.md) — the five-class Triage rubric for hard-coded literals: named obligation, unnamed obligation, ecosystem convention, magic-constant duplication, coincidence.
- [Self-sufficient claims and the Claim Builder](concepts/self-sufficient-claims.md) — how claims are mechanically assembled to be Triage-decidable in one shot; bootstrap from exploration; positional vs semantic division of labor; shadow-doc-primary substrate.

## Decisions

- [0002 — Language choice: Python (with a sidecar door open)](decisions/0002-language-choice.md) — why osoji stays in Python for v1.
- [0003 — Distribute osoji-wiki as a Claude Code plugin](decisions/0003-plugin-packaging.md) — supersedes the manual install workflow from spec 0002 with `/plugin install osoji-wiki@osojicode`.

## Detectors

_(none yet — populated as detectors are migrated to the unified Finding/Triage architecture in v1 step 5)_

## Sources

_(none yet — populated as external references are cited)_

## How to use this wiki

- **Starting work?** Run `/brief <topic>` to load relevant pages into your session context.
- **Finishing a session?** Run `/debrief` to capture decisions, refined concepts, or detector notes back to the wiki.
- **Manual edits?** Open a PR against this directory like any other code change. Branch protection applies.
