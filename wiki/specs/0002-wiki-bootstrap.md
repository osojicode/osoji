---
id: "0002"
title: Wiki Bootstrap — osoji-wiki MCP server and seed content
type: spec
status: accepted
created: 2026-04-29
updated: 2026-04-29
related: [specs/0001-v1-foundation.md, decisions/0002-language-choice.md, concepts/three-gap-theory.md]
---

## Context

Step 1 of the [v1 foundation plan](0001-v1-foundation.md) called for creating the wiki — both the tooling and the seed content — in a single bootstrap session. The wiki has two parts:

1. **Pages** (the content) — markdown files that capture concepts, specs, decisions, detector designs, and external sources. These live inside the osoji repo at `wiki/` so they version alongside the code they describe.
2. **Tooling** (an MCP server + brief/debrief skills) — a sibling repo (`osoji-wiki`) that exposes `wiki_read`, `wiki_edit`, `wiki_write`, `wiki_delete`, `wiki_move`, `wiki_list` tools to Claude with content-addressable safety (CAS via SHA-256) so multiple agents can edit the wiki without clobbering each other.

The v1 plan called the tooling repo `osoji-wiki-mcp`. The user chose the shorter name `osoji-wiki` during the bootstrap session.

The intended outcome of this session: a private GitHub repo `osojicode/osoji-wiki` containing a working MCP server with the six tools, two skill stubs (`brief`, `debrief`), and tests; plus this `wiki/` tree inside the osoji repo with `SCHEMA.md`, `index.md`, `log.md`, the directory layout, and four seed entries.

## Decisions baked into this spec

| Decision | Choice | Reason |
|---|---|---|
| Tooling repo name | `osoji-wiki` (under `osojicode` org) | User preference; consistent with `osoji`, `osoji-brand`, `osoji-teams` |
| Visibility | Private | User-specified |
| Python package name | `osoji_wiki` | Matches repo; underscore-form for Python import |
| MCP framework | `mcp` (the official Python SDK) | Standard |
| Wiki root discovery | CLI arg `--wiki-root` (required) | Explicit > magical env var; multi-wiki support |
| CAS hash | SHA-256 of body bytes (frontmatter excluded) | Stable across `updated:` / `status:` bumps |
| Atomic write | tempfile in same dir + `os.replace` | Cross-platform atomic on same filesystem |
| Per-file lock | `asyncio.Lock` keyed by absolute path | Single-process MCP server; sufficient for v1 |
| brief/debrief shape | Skill markdown only (no MCP prompts in v1) | Short `/brief` `/debrief` slash commands; single source of truth |
| Wiki seed strategy | Author the four entries directly (not via MCP server) | Server doesn't exist at seed time; bootstrapping problem |
| Lock files for osoji-wiki | Single `requirements.lock` (no dev/tools split) | Small project; three-lock-file convention is overkill |

## What was created

### `osoji-wiki` repo (private, on GitHub)

Layout:

```
osoji-wiki/
├── .github/workflows/ci.yml        # pytest matrix on 3.11/3.12/3.13
├── LICENSE                         # Apache-2.0 (matches osoji)
├── README.md
├── pyproject.toml                  # hatchling, py>=3.11, console-script `osoji-wiki`
├── src/osoji_wiki/
│   ├── __main__.py                 # python -m osoji_wiki
│   ├── server.py                   # MCP server entry — registers six wiki_* tools
│   ├── store.py                    # filesystem-backed page store
│   ├── concurrency.py              # CAS, atomic rename, per-path asyncio.Lock map
│   └── frontmatter.py              # parse / serialize / strip YAML frontmatter
├── skills/
│   ├── brief.md                    # /brief skill
│   └── debrief.md                  # /debrief skill
└── tests/                          # 24 tests, all green
```

### MCP server tool signatures

All paths are relative to the wiki root (configured at server start via `--wiki-root`). Returned `hash` is SHA-256 hex of the body excluding frontmatter.

```python
wiki_list(prefix: str = "") -> {"paths": list[str]}
wiki_read(path: str) -> {"path": str, "content": str, "frontmatter": dict, "hash": str}
wiki_write(path: str, content: str, frontmatter: dict | None = None) -> {"path": str, "hash": str}
wiki_edit(path: str, expected_hash: str, content: str, frontmatter: dict | None = None) -> {"path": str, "hash": str}
wiki_delete(path: str, expected_hash: str) -> {"path": str, "deleted": True}
wiki_move(from_path: str, to_path: str, expected_hash: str) -> {"from_path": str, "to_path": str, "moved": True}
```

### `wiki/` in the osoji repo (this directory)

```
osoji/wiki/
├── SCHEMA.md                       # page format and lifecycle
├── index.md                        # categorized list of pages
├── log.md                          # append-only changelog
├── concepts/three-gap-theory.md    # the unifying theoretical frame
├── specs/0001-v1-foundation.md     # the foundation rebuild plan
├── specs/0002-wiki-bootstrap.md    # this spec
├── decisions/0002-language-choice.md  # Python; sidecar door open
├── detectors/                      # empty; populated as detectors are migrated in v1 step 4
└── sources/                        # empty; populated as external references are cited
```

## Verification (what holds when this spec is "done")

1. `~/projects/osoji-wiki/` is a git repo with remote `https://github.com/osojicode/osoji-wiki.git` (private), `main` branch pushed.
2. `pytest` in `osoji-wiki/` is green; 24 tests cover write-then-read round-trip, edit with correct hash, edit with wrong hash (rejected), delete with wrong hash (rejected), move, list with prefix, frontmatter excluded from hash, parallel edits to same path serialize correctly.
3. `python -m osoji_wiki --wiki-root ~/projects/osoji/wiki` starts an MCP server on stdio without error.
4. `osoji/wiki/` exists on a `wiki-bootstrap` feature branch, contains `SCHEMA.md`, `index.md`, `log.md`, and the four seed entries; every seed entry has valid frontmatter per `SCHEMA.md`.
5. `index.md` lists the four seed entries; `log.md` has one entry per page (date 2026-04-29, `bootstrap` tag in summary).
6. The user can invoke (manually or via skill) `wiki_read("specs/0001-v1-foundation.md")` and get the v1 plan body back with a stable hash.

## Out of scope (deferred)

- Installing the brief/debrief skills into Claude Code's skill directory (`~/.claude/skills/`) or registering the MCP server in Claude Code settings — left to the user to do explicitly.
- Multi-process / multi-host wiki MCP semantics; single-host single-process is sufficient for v1.
- Auto-PR of the osoji `wiki/` bootstrap; the branch is pushed but the PR is opened by the user (or as a separate confirmed action).

## Resolved open questions

1. **GitHub org for the new repo:** `osojicode` (matches `osojicode/osoji`). Repo: `git@github.com:osojicode/osoji-wiki.git`, private.
2. **Scope of the bootstrap session:** Tooling **and** content seed — both the `osoji-wiki` repo and this `wiki/` bootstrap.
3. **brief/debrief surface:** Skills only — markdown files in `osoji-wiki/skills/`, no MCP prompts.
4. **MCP server registration in Claude Code settings:** Out of scope for this session.
