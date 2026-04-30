---
id: "0003"
title: Distribute osoji-wiki as a Claude Code plugin
type: decision
status: accepted
created: 2026-04-29
updated: 2026-04-29
related: [specs/0002-wiki-bootstrap.md]
---

## Context

The wiki bootstrap (spec 0002) shipped osoji-wiki as a normal Python package: contributors ran `pip install -e ".[dev]"`, registered the MCP server with `claude mcp add`, and copied the brief/debrief skill files into `~/.claude/skills/`. None of that state was version-controlled. A machine move broke the workflow; updating the server required manual re-registration; the skills got out of sync if the user edited one copy.

## Decision

Ship osoji-wiki as a Claude Code plugin. The repository is both the marketplace and the plugin (`.claude-plugin/marketplace.json` lists a single plugin at `source: "./"`). End-user install is two commands inside Claude Code:

```
/plugin marketplace add osojicode/osoji-wiki
/plugin install osoji-wiki@osojicode
```

The installer prompts for `wiki_root` (a `userConfig` field of type `directory`) and persists the value in `settings.json` under `pluginConfigs["osoji-wiki@osojicode"].options`. A `SessionStart` hook creates a private venv under `${CLAUDE_PLUGIN_DATA}/venv` and `pip install`s `mcp`, `click`, `pyyaml` into it on first use; subsequent sessions reuse it. The MCP server is auto-registered. Skills are namespaced as `/osoji-wiki:brief` and `/osoji-wiki:debrief`.

## Sub-decisions

| Question | Choice | Why |
|---|---|---|
| Skill layout | `skills/<name>/SKILL.md` (subdir) | Required by plugin spec; flat `skills/<name>.md` is rejected |
| Cross-platform setup | Python launcher scripts (`scripts/install.py`, `scripts/run.py`) | `plugin.json` is static JSON — no OS-conditional values. Python handles `Scripts/python.exe` vs `bin/python` via `sys.platform` |
| Venv location | `${CLAUDE_PLUGIN_DATA}/venv` | Survives plugin updates; `${CLAUDE_PLUGIN_ROOT}` does not |
| Plugin source install | `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/src` in launcher | Avoids `pip install -e` of plugin source; only third-party deps go in venv |
| Setup idempotence | Marker file `${CLAUDE_PLUGIN_DATA}/.installed-version` = SHA-256 of `requirements.txt` | Hook runs every session start; no-op when marker matches |
| Marketplace name | `osojicode` (the org) | Canonical install command becomes `osoji-wiki@osojicode` instead of awkward `osoji-wiki@osoji-wiki` |

## Alternatives considered

- **Bash-based SessionStart hook** with platform detection. Rejected: Git Bash on Windows is not guaranteed; Python is already required for the server itself.
- **Wrapper Python script that's the MCP `command` directly** (no venv). Rejected: pollutes the user's system Python with plugin deps.
- **Bundle the plugin's own source into the venv via `pip install -e ${CLAUDE_PLUGIN_ROOT}`**. Rejected: `${CLAUDE_PLUGIN_ROOT}` changes on plugin updates, leaving the venv pointing at a stale path. PYTHONPATH manipulation is simpler and survives updates because the launcher resolves the current root each invocation.
- **Symlinks for the brief/debrief skills**. Rejected upstream of the plugin work: Git Bash on Windows fell back to copies without Developer Mode.

## Consequences

- Slash commands change: `/brief` and `/debrief` are now `/osoji-wiki:brief` and `/osoji-wiki:debrief`. Plugin skills are always namespaced.
- The previously registered MCP server (project-scoped, pointing at a local `.venv`) and the user-level skill copies (`~/.claude/skills/{brief,debrief}.md`) must be removed once on each machine that had the manual install.
- Plugin updates land via `/plugin update osoji-wiki@osojicode` — no per-machine work required.
- A fresh machine needs only Python 3.11+ on PATH plus the two install commands; everything else is automatic.

## Sources

- Claude Code plugins overview: https://code.claude.com/docs/en/plugins.md
- Plugin manifest reference: https://code.claude.com/docs/en/plugins-reference.md
- Plugin discovery and install: https://code.claude.com/docs/en/discover-plugins.md
- Plugin marketplaces: https://code.claude.com/docs/en/plugin-marketplaces.md
