# Docstar

AI-powered documentation and code quality auditing tool. Uses Anthropic Claude to
generate shadow documentation, extract structured facts, and detect code issues.

## Build & test

```bash
pip install -e ".[dev]"    # install with dev dependencies
pytest                     # full suite
pytest tests/test_facts.py -v  # single module
```

## Shadow docs (.docstar/shadow/)

Every source file has a corresponding `.shadow.md` in `.docstar/shadow/` that
summarises purpose, key components, dependencies, and design notes. Directory-level
`_root.shadow.md` files aggregate their children.

**For coding agents**: read shadow docs instead of parsing entire files. They give you
the same structural understanding in a fraction of the tokens:
- `_root.shadow.md` — project/directory overview
- `<file>.shadow.md` — per-file summary with line references

The pre-commit hook runs `docstar safety check` (blocks on failure) then
`docstar check` which marks stale docs with warning lines and writes
`.docstar/staleness.json`, but does not regenerate them (no LLM calls).
Run `docstar shadow .` explicitly to regenerate.
Use `docstar check --dry-run` for a read-only report without file modifications.

## Structured facts (.docstar/facts/)

Each source file also gets a `.facts.json` with machine-readable metadata:
imports, exports, calls, and string literals. The `FactsDB` class in
`src/docstar/facts.py` loads these and provides query methods for import graphs,
export analysis, and string contract checking.

**Note**: facts data comes from LLM extraction and may contain malformed entries
(e.g. plain strings where dicts are expected). The `_only_dicts()` filter in
`_load()` handles this defensively.

## Key architecture

- `src/docstar/cli.py` — Click CLI with subcommands: `shadow`, `check` (`--dry-run`), `diff`, `stats`, `audit`, `report`, `hooks`, `safety`, `viz`
- `src/docstar/config.py` — Configuration, path helpers, model tier constants
- `src/docstar/shadow.py` — Core shadow doc generation engine
- `src/docstar/audit.py` — Multi-phase audit orchestration
- `src/docstar/llm/` — LLM provider abstraction (Anthropic), validation, token counting
- `src/docstar/rate_limiter.py` — Token-bucket rate limiter for API calls
- `src/docstar/facts.py` — Structured facts database and queries
- `src/docstar/symbols.py` — Symbol extraction and loading from `.docstar/symbols/`
- `src/docstar/obligations.py` — String contract / obligation checking
- `src/docstar/tools.py` — Tool definitions (schemas) for LLM tool use
- `src/docstar/doc_analysis.py` — Documentation accuracy analysis
- `src/docstar/deadcode.py` — Dead code detection
- `src/docstar/plumbing.py` — Dead plumbing detection (unactuated config obligations)
- `src/docstar/junk.py` — Junk code analysis (with `junk_cicd.py`, `junk_deps.py`, `junk_orphan.py`)
- `src/docstar/scorecard.py` — Audit scorecard generation
- `src/docstar/safety/` — Pre-commit safety checks (personal path detection, filters)
- `src/docstar/walker.py` — Repository file discovery (git ls-files / fallback walk)
- `src/docstar/hooks.py` — Git hook installation and management
- `src/docstar/viz.py` — Visualization server; serves `viz.html` dashboard

## Style

- Python 3.11+, type hints throughout
- Tests use pytest with `tmp_path` fixtures and `unittest.mock`
- Async where needed (LLM calls), sync otherwise
- Commit messages: imperative mood, concise
