# Osoji

AI-powered documentation and code quality auditing tool. Uses Anthropic Claude to
generate shadow documentation, extract structured facts, and detect code issues.

## Build & test

```bash
pip install -e ".[dev]"    # install with dev dependencies
pytest                     # full suite
pytest tests/test_facts.py -v  # single module
```

## Workflow: all changes through PRs

Branch protection on `main` requires passing CI status checks. Direct pushes
are blocked — even for the repo owner.

```bash
git checkout -b <branch-name>
# ... make changes, run tests locally ...
git add <files>
git commit -m "imperative mood description"
git push -u origin <branch-name>
gh pr create --fill
```

Do NOT auto-merge. The project owner reviews PR summaries and merges manually
(`gh pr merge <number> --squash` or via the GitHub UI). Releases are also
manual — the owner creates a GitHub Release, which triggers the publish
workflow.

When updating project dependencies:
1. Edit `pyproject.toml`
2. Regenerate both project lock files:
   - `uv pip compile pyproject.toml --generate-hashes --universal -o requirements.lock`
   - `uv pip compile pyproject.toml --extra dev --generate-hashes --universal -o requirements-dev.lock`
3. Commit all three files in the same PR

When updating CI tooling (pip-audit, uv, build):
1. Edit `requirements-tools.in`
2. Regenerate: `uv pip compile requirements-tools.in --generate-hashes --universal -o requirements-tools.lock`
3. Commit both files in the same PR

CI installs from all three lock files with `--require-hashes` and runs a
freshness gate that fails if any committed lock is out of sync with its
source. Skipping the regenerate step blocks the PR.

See `SUPPLY-CHAIN-SECURITY.md` for the full governance model and threat model.

## Wiki and session workflow

Design rationale, decisions, concepts, and detector notes that survive across
agent sessions live in `wiki/` (see `wiki/SCHEMA.md` for page format and
lifecycle). The wiki is the canonical archive — non-trivial decisions and
concepts belong there, not in commit messages or in this file.

Tooling lives in the sibling [osoji-wiki](https://github.com/osojicode/osoji-wiki)
repo, distributed as a Claude Code plugin (`/plugin marketplace add
osojicode/osoji-wiki && /plugin install osoji-wiki@osojicode`). The plugin
provides an MCP server with content-addressable read/write tools so concurrent
agent edits don't clobber each other, plus two namespaced slash-command skills:

- `/osoji-wiki:brief <topic>` — load relevant wiki pages into a session at start
- `/osoji-wiki:debrief` — capture decisions, concepts, or detector notes back
  to the wiki at session end

Use `/osoji-wiki:brief` when starting non-trivial work; use `/osoji-wiki:debrief`
when finishing a session that produced something worth preserving past the next
compaction.

## Shadow docs (.osoji/shadow/)

Every source file has a corresponding `.shadow.md` in `.osoji/shadow/` that
summarises purpose, key components, dependencies, and design notes. Directory-level
roll-up docs aggregate their children: `_root.shadow.md` at the project root,
`_directory.shadow.md` in subdirectories.

**For coding agents**: read shadow docs instead of parsing entire files. They give you
the same structural understanding in a fraction of the tokens:
- `_root.shadow.md` — project root overview
- `_directory.shadow.md` — subdirectory overview
- `<file>.shadow.md` — per-file summary with line references

The pre-commit hook runs `osoji safety check` (blocks on failure) then
`osoji check .` which marks stale docs with warning lines and writes
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

- `src/osoji/cli.py` — Click CLI with subcommands: `init`, `shadow`, `check` (`--dry-run`), `diff`, `stats`, `audit`, `report`, `export`, `push`, `hooks`, `safety`, `config show`, `skills list|show`
- `src/osoji/init.py` — Interactive project setup (gitignore, .env, .osoji.toml merge)
- `src/osoji/config.py` — Configuration, path helpers, model tier constants
- `src/osoji/shadow.py` — Core shadow doc generation engine
- `src/osoji/audit.py` — Multi-phase audit orchestration
- `src/osoji/llm/` — LLM provider abstraction (Anthropic, OpenAI, Google, OpenRouter via LiteLLM; Claude Code via CLI), validation, token counting
- `src/osoji/rate_limiter.py` — Reservation-based async rate limiter (RPM + input/output TPM)
- `src/osoji/facts.py` — Structured facts database and queries
- `src/osoji/symbols.py` — Symbol loading and querying from `.osoji/symbols/`
- `src/osoji/obligations.py` — String contract / obligation checking
- `src/osoji/tools.py` — Tool definitions (schemas) for LLM tool use
- `src/osoji/doc_analysis.py` — Documentation accuracy analysis
- `src/osoji/deadcode.py` — Dead code detection
- `src/osoji/deadparam.py` — Dead parameter detection
- `src/osoji/plumbing.py` — Dead plumbing detection (unactuated config obligations)
- `src/osoji/junk.py` — Junk code analysis (with `junk_cicd.py`, `junk_deps.py`, `junk_orphan.py`)
- `src/osoji/scorecard.py` — Audit scorecard generation
- `src/osoji/safety/` — Pre-commit safety checks (personal path and secret scanning, filters)
- `src/osoji/walker.py` — Repository file discovery (git ls-files / fallback walk)
- `src/osoji/hasher.py` — SHA-256 hashing and Merkle staleness detection
- `src/osoji/diff.py` — Git diff documentation impact analysis
- `src/osoji/stats.py` — Token counting statistics
- `src/osoji/push.py` — Push observatory bundle to osoji-teams ingest API
- `src/osoji/hooks.py` — Git hook installation and management
- `src/osoji/observatory.py` — Observatory bundle assembly for export
- `src/osoji/async_utils.py` — Async runtime helpers
- `src/osoji/doc_prompts.py` — Concept-centric documentation coverage and writing prompt generation
- `src/osoji/plugins/` — Language-specific AST extraction plugins (Python, TypeScript)
- `src/osoji/skills/` — Bundled AI agent skill prompts (markdown files with YAML frontmatter); also mirrored at `.claude/skills/<name>/SKILL.md` for Claude Code agents working on this repo (parity enforced by `tests/test_skills_parity.py`)
- `src/osoji/osoji-observatory.schema.json` — JSON Schema (Draft 2020-12) for the observatory bundle

## Observatory bundle schema

`src/osoji/osoji-observatory.schema.json` is the authoritative contract for
the bundle shape produced by `osoji export`. It uses JSON Schema Draft 2020-12.

- **Updating**: when `observatory.py` adds or changes bundle fields, mirror
  the change in the schema file and add a schema validation test.
- **osoji-teams**: the ingest API and dashboard consume this schema. Coordinate
  schema changes with the osoji-teams repo.
- **Validation**: schema validation lives exclusively in `tests/test_observatory.py`
  using `jsonschema`. There is no runtime validation in `observatory.py`.

## Push configuration

The `osoji push` command reads `[push]` config from three files (later overrides earlier):
- `~/.config/osoji/config.toml` — global defaults
- `.osoji.toml` — committed project config (project, endpoint)
- `.osoji.local.toml` — gitignored local overrides (endpoint, project)

CLI flags and environment variables (`OSOJI_ENDPOINT`, `OSOJI_TOKEN`) take highest precedence.
Secrets (`OSOJI_TOKEN`, API keys) go in `.env` — loaded automatically, never committed.
In non-quiet mode, `osoji push` prints which source each config value was resolved from.

## LLM parameters

- **Temperature**: `CompletionOptions.temperature` defaults to `None` (omit from request,
  letting each provider use its own default). Do NOT set `temperature=0.0` — it breaks
  models that reject explicit zero (e.g. gpt-5) and provides no benefit for structured
  tool-use outputs where the JSON schema constrains the response. If a call site needs
  explicit temperature control, pass a non-zero value.

## Pipeline engineering principles

- **Language agnosticism is non-negotiable.** All detection logic, system prompts,
  candidate scanning heuristics, and post-processing filters must work identically
  for any programming language. Never introduce patterns that assume Python conventions
  (e.g. `test_` prefix for test files, `__init__.py` for packages, decorators for
  framework registration). When dogfooding osoji on itself, be especially vigilant —
  solutions that fix a Python false positive may break detection for Go, Rust, or Java.

- **Principles over catalogs in LLM prompts.** When instructing the LLM what to
  extract, skip, or classify, describe the *principle* (e.g. "skip ecosystem convention
  strings that couldn't form project-specific contracts") rather than enumerating
  specific items (e.g. "skip python, javascript, .py, node_modules"). The LLM already
  knows what ecosystem conventions are — a hardcoded list adds no information and
  creates failure modes: it can never be exhaustive, expanding it destabilizes
  classification by conflicting with other prompt instructions, and it tends to encode
  language-specific assumptions (violating language agnosticism). Anti-pattern: if
  you're tempted to add items to a skip/include list in a prompt, check whether the
  surrounding principle is stated clearly enough instead.

- **Signal conservation.** Every change to reduce false positives must be evaluated for
  its impact on true positives, and vice versa. Frame proposals as: "This change would
  prevent N false positives of type X. Could it suppress true positives? Under what
  conditions?" If the answer is unclear, prefer keeping the finding and adjusting its
  severity/confidence rather than suppressing it entirely.

- **Facts DB is noisy — use LLM reasoning to filter.** LLM-extracted `.facts.json`
  data may contain malformed entries, misclassified strings, or missing references.
  Never use facts mechanically to suppress findings (e.g. "if referenced anywhere,
  dismiss"). Instead, present facts as evidence to the LLM and let it reason about
  whether the references represent genuine usage. The LLM can distinguish real imports
  from name collisions, comments, or string literals — a mechanical filter cannot.

- **Implicit contracts: surface silent failures.** When two files share a string
  literal (e.g. a dict key), renaming in one silently breaks the other at runtime
  (a value-level error). When both import a shared constant, a rename causes an
  ImportError or NameError at load time (a name-level error). The obligation checker
  exists to find these implicit string contracts. Remediation text should explain
  this distinction — the goal is to convert silent value-level mismatches into loud
  name-level errors, not merely to "extract constants."

- **Closed-set taxonomies require an `other` outlet, and `other`-rate is itself
  a metric.** Whenever the system introduces a closed-set classification (gap
  types, string-contract classes, evidence kinds, severity scales), include
  an explicit `other`/`uncategorized` value as a safety valve. The downstream
  handler treats `other` as a request for review rather than silently shoehorning
  into the closest fit. The proportion of items routed to `other` is then a
  first-class metric on the taxonomy's adequacy: rising rate signals revision.
  This is how taxonomies stay falsifiable engineering claims rather than
  ossifying into asserted theorems. See `wiki/specs/0001-v1-foundation.md#epistemological-note`.

- **Mechanical layers gather; LLM layers reason; both are answerable to the
  regression evaluator.** Where to put the boundary between mechanical
  (cheap, exhaustive, reliable) and LLM (judgment, world knowledge) is decided
  per-task by measurement, not by rule. The Claim Builder is allowed to be
  ignorant of stdlib semantics (the LLM has world knowledge in its weights);
  the LLM is allowed to be ignorant of cross-file reference graphs (the
  mechanical layer has the FactsDB). Both layers report to the regression
  evaluator, which is what tells us whether a given division is working.

## Style

- Python 3.11+, type hints throughout
- Tests use pytest with `tmp_path` and custom `temp_dir` fixtures and `unittest.mock`
- Async where needed (LLM calls), sync otherwise
- Commit messages: imperative mood, concise
