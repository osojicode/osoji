# Osoji

AI-powered documentation and code quality auditing tool. Uses Anthropic Claude to
generate shadow documentation, extract structured facts, and detect code issues.

## Build & test

```bash
pip install -e ".[dev]"    # install with dev dependencies
pytest                     # full suite
pytest tests/test_facts.py -v  # single module
```

## Shadow docs (.osoji/shadow/)

Every source file has a corresponding `.shadow.md` in `.osoji/shadow/` that
summarises purpose, key components, dependencies, and design notes. Directory-level
`_root.shadow.md` files aggregate their children.

**For coding agents**: read shadow docs instead of parsing entire files. They give you
the same structural understanding in a fraction of the tokens:
- `_root.shadow.md` — project/directory overview
- `<file>.shadow.md` — per-file summary with line references

The pre-commit hook runs `osoji safety check` (blocks on failure) then
`osoji check` which marks stale docs with warning lines and writes
`.osoji/staleness.json`, but does not regenerate them (no LLM calls).
Run `osoji shadow .` explicitly to regenerate.
Use `osoji check --dry-run` for a read-only report without file modifications.

## Structured facts (.osoji/facts/)

Each source file also gets a `.facts.json` with machine-readable metadata:
imports, exports, calls, and string literals. The `FactsDB` class in
`src/osoji/facts.py` loads these and provides query methods for import graphs,
export analysis, and string contract checking.

**Note**: facts data comes from LLM extraction and may contain malformed entries
(e.g. plain strings where dicts are expected). The `_only_dicts()` filter in
`_load()` handles this defensively.

## Key architecture

- `src/osoji/cli.py` — Click CLI with subcommands: `shadow`, `check` (`--dry-run`), `diff`, `stats`, `audit`, `report`, `hooks`, `safety`, `viz`
- `src/osoji/config.py` — Configuration, path helpers, model tier constants
- `src/osoji/shadow.py` — Core shadow doc generation engine
- `src/osoji/audit.py` — Multi-phase audit orchestration
- `src/osoji/llm/` — LLM provider abstraction (Anthropic), validation, token counting
- `src/osoji/rate_limiter.py` — Token-bucket rate limiter for API calls
- `src/osoji/facts.py` — Structured facts database and queries
- `src/osoji/symbols.py` — Symbol extraction and loading from `.osoji/symbols/`
- `src/osoji/obligations.py` — String contract / obligation checking
- `src/osoji/tools.py` — Tool definitions (schemas) for LLM tool use
- `src/osoji/doc_analysis.py` — Documentation accuracy analysis
- `src/osoji/deadcode.py` — Dead code detection
- `src/osoji/plumbing.py` — Dead plumbing detection (unactuated config obligations)
- `src/osoji/junk.py` — Junk code analysis (with `junk_cicd.py`, `junk_deps.py`, `junk_orphan.py`)
- `src/osoji/scorecard.py` — Audit scorecard generation
- `src/osoji/safety/` — Pre-commit safety checks (personal path detection, filters)
- `src/osoji/walker.py` — Repository file discovery (git ls-files / fallback walk)
- `src/osoji/hooks.py` — Git hook installation and management
- `src/osoji/viz.py` — Visualization server; serves `viz.html` dashboard

## Style

- Python 3.11+, type hints throughout
- Tests use pytest with `tmp_path` fixtures and `unittest.mock`
- Async where needed (LLM calls), sync otherwise
- Commit messages: imperative mood, concise
