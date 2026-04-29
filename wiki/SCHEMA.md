# Wiki page schema

Every page in this wiki is a Markdown file with YAML frontmatter. The frontmatter is the contract that tooling (the [`osoji-wiki`](https://github.com/osojicode/osoji-wiki) MCP server, the `/brief` and `/debrief` skills) reads and writes; the body is what humans and agents read.

## Frontmatter (required keys)

```yaml
---
id: "0001"
title: V1 Foundation — Unified Finding/Triage Architecture
type: spec | concept | decision | detector | source
status: draft | accepted | superseded
created: 2026-04-29
updated: 2026-04-29
related: [concepts/three-gap-theory.md, decisions/0002-language-choice.md]
---
```

| Key | Type | Description |
|---|---|---|
| `id` | 4-digit string, quoted | Unique within `type`. New entries increment past the highest existing id of the same type. |
| `title` | string | One-line, human-readable. |
| `type` | enum | `spec`, `concept`, `decision`, `detector`, or `source`. |
| `status` | enum | `draft` (in flux), `accepted` (settled), `superseded` (overridden by a newer page). |
| `created` | ISO date | First write date. Never changes. |
| `updated` | ISO date | Last meaningful edit. Bump when content (not just frontmatter) changes. |
| `related` | list of paths | Other wiki pages this depends on, references, or supersedes. Used by `/brief` to discover context. |

The MCP server's content-addressable safety hash covers **body bytes only** — frontmatter changes (e.g. bumping `updated:` or moving from `draft` → `accepted`) do not invalidate readers' hashes.

## Directory layout

| Subdir | What goes here |
|---|---|
| `concepts/` | Defined terms used throughout the project (e.g. "three-gap theory", "Finding schema"). One concept per page. |
| `specs/` | Numbered specifications for substantial pieces of work (e.g. `0001-v1-foundation.md`). |
| `decisions/` | Numbered ADR-style decisions: a problem statement, the choice made, the alternatives, and the reason. |
| `detectors/` | One page per audit detector. Records its declared context-window class (per-file, project-graph, file-tuple), gap type, evidence kinds consumed, and known FP modes. |
| `sources/` | External references: papers, articles, OSS scanner docs that informed decisions or detector design. |

`index.md` lists every page categorized by directory. `log.md` is the append-only changelog of wiki edits.

## Body conventions

- Markdown rendered by GitHub.
- Internal links use repo-relative paths starting from the wiki root: `[three-gap theory](concepts/three-gap-theory.md)`.
- Code references in osoji should include the file path so they remain navigable from the GitHub UI: `src/osoji/audit.py:262-399`.
- Headings start at `##` (the title is in frontmatter, not the body).
- Tables, code blocks, and short paragraphs are preferred over long prose.

## Lifecycle

1. **Draft.** A new page is written with `status: draft`. The author and reviewers iterate on the body; `updated:` bumps with each substantive edit.
2. **Accepted.** Once the page is settled (the spec is approved, the decision is final, the concept is stable), `status: accepted`. Subsequent edits should be small and additive.
3. **Superseded.** When a newer page replaces this one, `status: superseded`. Add a `superseded_by:` key pointing at the replacement. The page stays in the wiki for historical context — link rot is worse than stale content.

## Adding a page

The intended path is via `/debrief`, which runs through the MCP server's `wiki_write` tool and updates `index.md` + `log.md` automatically. Direct filesystem writes are also fine for the bootstrap and for trivial fixes — the schema is the contract, not the tooling.
