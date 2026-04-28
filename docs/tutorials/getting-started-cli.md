# Getting Started with the Osoji CLI

This tutorial walks you through your first experience with the Osoji
command-line tool. You will install the package, generate shadow documentation
for a project, run an audit, and explore the other subcommands -- all from the
terminal.

**Time estimate**: 20-30 minutes.

---

## Prerequisites

Before you begin, make sure you have:

- **Python 3.11 or later**. Verify with:

  ```bash
  python --version
  ```

- **A project repository** to analyze. Any small-to-medium codebase works. If
  you do not have one handy, clone an open-source repository with 10-30 source
  files.

- **An LLM API key** from at least one supported provider:
  - Anthropic (`ANTHROPIC_API_KEY`)
  - OpenAI (`OPENAI_API_KEY`)
  - Google Gemini (`GEMINI_API_KEY`)
  - OpenRouter (`OPENROUTER_API_KEY`)

Export the key in your shell before continuing:

```bash
export ANTHROPIC_API_KEY=your-api-key-here
```

---

## Step 1: Install Osoji

The package is published on PyPI under the name `osojicode`. The CLI command
it installs is `osoji`.

### Option A: pip (into a virtual environment)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install osojicode
```

### Option B: pipx (isolated install, no venv needed)

```bash
pipx install osojicode
```

### Option C: editable install (for contributors)

If you have the Osoji source tree:

```bash
pip install -e ".[dev]"
```

The entry point is defined in `pyproject.toml` as:

```toml
[project.scripts]
osoji = "osoji.cli:main"
```

This means the `osoji` command invokes `osoji.cli:main` -- the Click-based CLI
group that routes to all subcommands.

### Verify the installation

```bash
osoji --version
```

You should see output like:

```
osoji, version 0.2.0
```

---

## Step 2: Explore the command tree

Run the top-level help to see every available subcommand:

```bash
osoji --help
```

Expected output:

```
Usage: osoji [OPTIONS] COMMAND [ARGS]...

  Osoji -- The garbage collector for AI-assisted codebases.

  Audit your project for dead code, stale documentation, and semantic
  contradictions. Ships with agent skill files for automated triage and fixing.

Options:
  --version      Show the version and exit.
  -v, --verbose  Show detailed output
  -q, --quiet    Suppress nonessential diagnostic output
  --help         Show this message and exit.

Commands:
  audit       Audit your codebase for dead code, stale docs, and semantic...
  check       Check for stale or missing shadow documentation.
  config      Inspect resolved Osoji configuration.
  diff        Show documentation impact of source changes.
  export      Export a stable, versioned observatory bundle for downstream...
  hooks       Manage git hooks for automatic shadow doc updates.
  init        Set up osoji for this project.
  push        Push observatory bundle to osoji-teams.
  report      Re-render the last audit result in a different format.
  safety      Pre-commit safety checks for personal paths and secrets.
  shadow      Generate shadow documentation (used internally by audit).
  skills      List and display bundled AI agent skill files.
  stats       Show token statistics for source files vs shadow docs.
```

### The `--verbose` and `--quiet` flags

Two global flags control output volume. They sit on the top-level `osoji`
group and apply to every subcommand:

| Flag | Effect |
|------|--------|
| `-v`, `--verbose` | Show detailed per-file progress, timing, and diagnostics |
| `-q`, `--quiet` | Suppress all nonessential diagnostic output |

These flags are **mutually exclusive**. If you pass both, Osoji exits with an
error:

```bash
osoji --verbose --quiet shadow .
# Error: Cannot use --verbose and --quiet together.
```

Internally, the combination is tracked through a `CLIState` dataclass that
every subcommand inherits. You do not need to think about this -- just
remember that `-v` gives more detail and `-q` gives less.

### Verification checkpoint

At this point you should be able to:

1. Run `osoji --version` and see a version number.
2. Run `osoji --help` and see the subcommand list above.
3. Have your LLM API key exported in the current shell.

If all three check out, you are ready to set up your project.

---

## Step 2b: Initialize your project (recommended)

Run `osoji init` to set up configuration for your project:

```bash
osoji init
```

This walks you through:
- Adding osoji entries to `.gitignore` (`.osoji/`, `.osoji.local.toml`, `.env`)
- Setting your LLM API key in `.env`
- Configuring a project slug in `.osoji.toml` for `osoji push`

Each step prompts for confirmation with sensible defaults -- press Enter to
accept them all.

For scripted or CI environments, use `--non-interactive` to write template
files with commented-out placeholders:

```bash
osoji init --non-interactive
```

If you use a provider other than Anthropic:

```bash
osoji init --provider openai
```

If you already have a `.env` or `.osoji.toml`, `osoji init` will merge missing
keys without overwriting existing values.

---

## Step 3: Generate shadow documentation

Shadow documentation is Osoji's core concept: for each source file in your
project, Osoji generates a semantically dense summary stored as a sidecar
Markdown file under `.osoji/shadow/`. These summaries capture purpose,
structure, dependencies, and code-quality findings.

Navigate to the root of the project you want to analyze:

```bash
cd /path/to/your-project
```

### 3a: Preview with `--dry-run`

Before making LLM calls, preview what Osoji would process:

```bash
osoji shadow --dry-run .
```

Expected output (details vary by project):

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
Dry run for: /path/to/your-project

Impl hash: a1b2c3d4e5f67890
Total source files: 12
  Would generate: 12
  Already cached:  0
Directories: 3

Estimated tokens (for 12 file(s) to generate):
  Input:  ~14,500
  Output: ~3,770
Estimated cost: ~$0.10
```

This tells you:

- How many source files Osoji discovered.
- How many would need generation (versus how many are already cached).
- Estimated token usage and cost.

Use `--verbose` for a per-file breakdown:

```bash
osoji --verbose shadow --dry-run .
```

This appends a file-by-file listing showing staleness reason and byte size:

```
Files to process (12):
  [missing] src/models/user.py  (2,340 bytes)
  [missing] src/models/order.py  (1,890 bytes)
  [missing] src/api/routes.py  (3,120 bytes)
  ...
```

### 3b: Run the full generation

When you are satisfied with the preview, run shadow generation for real:

```bash
osoji shadow .
```

You will see a configuration banner on stderr (showing the resolved
provider/model), followed by a progress bar:

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
  [1/12] 8% [ok] user.py
  [2/12] 17% [ok] order.py
  ...
  [12/12] 100% 14.5K^ 3.8Kv [ok] routes.py
```

The `14.5K^` and `3.8Kv` numbers are cumulative input and output token counts.

#### What just happened?

Osoji created a `.osoji/` directory at your project root containing:

```
.osoji/
  shadow/
    src/
      models/
        user.py.shadow.md
        order.py.shadow.md
        _directory.shadow.md
      api/
        routes.py.shadow.md
        _directory.shadow.md
    _root.shadow.md
  facts/
    src/
      models/
        user.py.facts.json
        order.py.facts.json
      ...
  symbols/
    src/
      models/
        user.py.symbols.json
        ...
  findings/
    src/
      models/
        user.py.findings.json
        ...
  signatures/
    src/
      models/
        user.py.signature.json
        ...
```

Key directories:

| Directory | Contents |
|-----------|----------|
| `shadow/` | Per-file `.shadow.md` summaries and per-directory `_directory.shadow.md` roll-ups |
| `facts/` | `.facts.json` with imports, exports, calls, string literals |
| `symbols/` | `.symbols.json` with function/class/constant definitions |
| `findings/` | `.findings.json` with code debris identified during generation |
| `signatures/` | `.signature.json` with topic signatures for coverage analysis |

### Using alternate providers

Osoji defaults to Anthropic. To use a different provider:

```bash
osoji shadow . --provider openai --model gpt-5.2
osoji shadow . --provider google --model gemini-2.0-flash
osoji shadow . --provider openrouter --model openai/gpt-5-mini
```

### Force regeneration

If you want to regenerate everything from scratch (ignoring cached hashes):

```bash
osoji shadow . --force
```

### Verification checkpoint

After generation completes, confirm:

1. A `.osoji/` directory exists at your project root.
2. It contains a `shadow/` subdirectory with `.shadow.md` files mirroring your
   source tree.
3. At least one `_directory.shadow.md` file exists (the directory roll-up).
4. A `_root.shadow.md` exists summarizing the entire project.

Open any `.shadow.md` file and confirm it contains a header with `@source-hash`,
`@impl-hash`, and `@generated` fields, followed by a readable summary of the
corresponding source file.

---

## Step 4: Run an audit

With shadow documentation in place, you can run a full audit to assess
documentation quality, accuracy, and code hygiene.

### 4a: Basic audit

```bash
osoji audit .
```

The audit runs in phases:

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
Osoji: Checking shadow documentation...
Osoji: Auto-updating 0 shadow doc(s)...
  [1/4] 25% [ok] README.md
  [2/4] 50% [ok] CONTRIBUTING.md
  [3/4] 75% [ok] docs/api.md
  [4/4] 100% 8.2K^ 2.1Kv [ok] CHANGELOG.md
Osoji: Building scorecard...
API tokens: 8,200^ 2,100v (10,300 total)
```

The phases execute as follows:

| Phase | Name | Execution | Description |
|-------|------|-----------|-------------|
| 1 | Shadow doc check/fix | Sequential | Updates stale shadow docs (prerequisite for later phases) |
| 2 | Doc analysis | Concurrent | Classifies docs by Diataxis type, validates accuracy via LLM |
| 3 | Debris verification | Concurrent | Verifies code debris findings from shadow generation against cross-file evidence via LLM |
| 3.5 | Obligation checking | Concurrent | Checks cross-file string contracts (pure Python, no LLM) |
| 4 | Junk analysis | Concurrent | Runs opt-in junk analyzers (dead code, dead params, etc.) |
| 5 | Scorecard | Sequential | Builds aggregate metrics from all phase results |
| 5.5 | Doc prompts | Sequential (optional) | Generates concept inventory and writing prompts |

Phases 2, 3, 3.5, and 4 run concurrently via `asyncio.gather`. A shared
`RateLimiter` coordinates LLM calls across all phases to respect provider
rate limits.

After completion, Osoji prints a Markdown report. A typical report looks like:

```
# Osoji Audit Passed

## Scorecard

Metric                       Value
---------------------------  -------------------------------------------
Source file coverage         75% (9/12 files)
Dead docs (debris)           1
Accuracy errors / live doc   0.33
Junk code fraction           2.1% (45 lines in 3 files)
Unactuated config            -- (not scanned)

### Doc linkage by type

*Fraction of docs of each type that link to at least one source file.*

Type          Linked  Total  %
------------  ------  -----  ---
explanatory   1       1      100%
how-to        2       2      100%
reference     1       2      50%
tutorial      0       1      0%

### Uncovered source files

- `src/utils/helpers.py` -- Internal utility functions
- `src/models/order.py` -- Order data model
- `src/config.py` -- Application configuration

### Dead documentation

- `docs/old-migration-guide.md`

### Accuracy errors by category

Category            Count
------------------  -----
outdated_reference  1

### Junk code by category

Category        Items  Lines
--------------  -----  -----
dead_code       2      30
stale_comment   1      15

*Phases not run: `--dead-code`, `--dead-params`, `--dead-plumbing`,
`--dead-deps`, `--dead-cicd`, `--orphaned-files`. Re-run with those flags
for a complete scorecard.*

## Warnings (non-blocking)

- `src/models/user.py`: L42-48: stale_comment -- comment references removed field

---
**Result**: 0 error(s), 1 warning(s), 0 info(s)
```

### 4b: Opt-in audit phases

The base audit always runs doc classification, accuracy validation, and code
debris detection. Additional analysis phases are opt-in:

```bash
# Detect cross-file dead code
osoji audit . --dead-code

# Detect dead function parameters
osoji audit . --dead-params

# Detect unactuated config/schema obligations
osoji audit . --dead-plumbing

# Detect unused package dependencies
osoji audit . --dead-deps

# Detect stale CI/CD pipeline elements
osoji audit . --dead-cicd

# Detect orphaned source files
osoji audit . --orphaned-files

# Run all junk analysis phases at once
osoji audit . --junk

# Check cross-file string contracts (no LLM calls)
osoji audit . --obligations

# Generate concept-centric coverage + writing prompts
osoji audit . --doc-prompts

# Run everything (equivalent to --junk --obligations --doc-prompts)
osoji audit . --full
```

### 4c: Output formats

The default output is Markdown printed to stdout. You can also produce HTML or
JSON reports:

**HTML report** (written to `.osoji/analysis/report.html`):

```bash
osoji audit . --format html
```

Output:

```
Report written to .osoji/analysis/report.html
```

Open this file in a browser to see an interactive, styled version of the
audit results.

**JSON report** (printed to stdout, for CI/programmatic use):

```bash
osoji audit . --format json
```

This produces structured JSON with `passed`, `errors`, `warnings`, `issues`,
`scorecard`, and optionally `doc_prompts` keys.

**Re-render without re-running** the audit:

```bash
osoji report . --format html
osoji report . --format json
osoji report .                  # text (default)
```

The `report` subcommand loads the cached audit result from the last run. No
LLM calls are made.

### Verification checkpoint

After your first audit:

1. The terminal shows a scorecard with coverage, accuracy, and junk metrics.
2. A `.osoji/analysis/` directory contains serialized results.
3. Running `osoji report .` reproduces the same report without new LLM calls.

---

## Step 5: Explore other commands

The following sections give a brief guided tour of the remaining Osoji
subcommands. Each is covered in more detail by dedicated tutorials and how-to
guides.

### 5a: `osoji diff` -- documentation impact of source changes

Compare current HEAD against a base ref and see which shadow docs are stale:

```bash
osoji diff                    # Compare against main
osoji diff develop            # Compare against develop
osoji diff HEAD~5             # Compare against 5 commits ago
osoji diff main --format json # Machine-readable output
```

To also regenerate stale shadow docs:

```bash
osoji diff main --update
```

Exit codes: `0` = no issues, `1` = issues found.

### 5b: `osoji safety` -- pre-commit safety checks

Osoji can scan files for personal filesystem paths and secrets before they
enter git history.

```bash
# Check all staged files
osoji safety check

# Check specific files
osoji safety check src/*.py

# View the regex patterns Osoji uses for path detection
osoji safety patterns

# Verify the Osoji package itself is clean
osoji safety self-test
```

For secret detection, install the optional `detect-secrets` dependency:

```bash
pip install 'osojicode[safety]'
```

### 5c: `osoji stats` -- codebase statistics

See how much compression shadow documentation provides:

```bash
osoji stats .
```

Sample output:

```
============================================================
OSOJI TOKEN STATISTICS
============================================================

Files analyzed:      12
Files with shadows:  12

Source tokens:       4,200
Shadow tokens:       1,680

Compression ratio:   40.00%
Token savings:       60.0%

============================================================
```

Use `--verbose` for a per-file breakdown:

```bash
osoji --verbose stats .
```

### 5d: `osoji hooks` -- git hook integration

Install git hooks to automate safety checks and staleness detection:

```bash
# Install pre-commit and pre-push hooks (defaults)
osoji hooks install

# Selective installation
osoji hooks install --no-pre-push            # pre-commit only
osoji hooks install --no-pre-commit --no-pre-push --post-commit  # post-commit only

# Remove all Osoji hooks
osoji hooks uninstall
```

The **pre-commit** hook runs `osoji safety check` (blocks on failure) and
`osoji check .` (marks stale docs, non-blocking). The **pre-push** hook warns
about stale shadow docs but does not block.

### 5e: `osoji config` -- inspect resolved configuration

See the effective provider/model configuration for a project:

```bash
osoji config show .
```

Output shows the resolved config with provenance (which file or default each
setting came from):

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
```

Configuration sources are checked in this precedence order:

1. CLI flags (`--provider`, `--model`)
2. Environment variables (`OSOJI_PROVIDER`, `OSOJI_MODEL_MEDIUM`)
3. Project-local `.osoji.local.toml` (gitignored)
4. Global `~/.config/osoji/config.toml`
5. Built-in defaults

### 5f: `osoji skills` -- AI agent skill files

Osoji ships with bundled skill prompts designed for AI coding agents:

```bash
# List available skills
osoji skills list
```

Output:

```
  osoji-sweep   Audit, triage every finding, fix true positives, file GitHub issues
  osoji-triage  Classify findings and produce a structured report
```

To view the full content of a skill:

```bash
osoji skills show osoji-sweep
```

These skills can be piped into AI agents:

```bash
osoji skills show osoji-sweep | pbcopy    # macOS
osoji skills show osoji-sweep | clip      # Windows
```

### 5g: `osoji export` -- observatory bundle

Export a stable, versioned observatory bundle for downstream consumers like
osoji-teams:

```bash
osoji export .
osoji export . --output observatory.json
```

The default output path is `.osoji/analysis/observatory.json`.

### 5h: `osoji push` -- push to osoji-teams

After exporting, push the bundle to the osoji-teams ingest API:

```bash
osoji push --project myproject
osoji push --token $OSOJI_TOKEN --endpoint https://custom.endpoint/api
```

Push configuration is read from `~/.config/osoji/config.toml`,
`.osoji.toml`, and `.osoji.local.toml`, with CLI flags and environment
variables (`OSOJI_ENDPOINT`, `OSOJI_TOKEN`) taking highest precedence.
Secrets (`OSOJI_TOKEN`, API keys) go in `.env` -- loaded automatically,
never committed. In non-quiet mode, `osoji push` prints which source each
config value was resolved from.

---

## Step 6: Understanding the `.osoji/` directory

After running `osoji shadow` and `osoji audit`, your project contains a
`.osoji/` directory with the following layout:

```
.osoji/
  shadow/                       # Shadow documentation
    _root.shadow.md             # Project root roll-up
    src/
      models/
        user.py.shadow.md       # Per-file shadow doc
        _directory.shadow.md    # Directory roll-up
  facts/                        # Structured metadata
    src/
      models/
        user.py.facts.json      # Imports, exports, calls, strings
  symbols/                      # Symbol definitions
    src/
      models/
        user.py.symbols.json    # Functions, classes, constants
  findings/                     # Code debris findings
    src/
      models/
        user.py.findings.json   # Dead code, stale comments, etc.
  signatures/                   # Topic signatures
    src/
      models/
        user.py.signature.json  # Purpose + topic keywords
  analysis/                     # Audit outputs (regenerated each run)
    report.html                 # HTML audit report
    observatory.json            # Observatory bundle
    docs/                       # Per-doc analysis results
    junk/                       # Per-analyzer junk results
  staleness.json                # Staleness manifest
  rules                         # Finding overrides (user-created)
```

### What to commit

By default, `osoji init` adds `.osoji/` to `.gitignore`, keeping generated
artifacts local. This is the simplest setup for solo use.

Teams who want to share shadow docs with AI agents and teammates can remove
the `.osoji/` entry from `.gitignore` and commit the directory. In that case,
the `analysis/` subdirectory is regenerated on each audit run, so committing
it is optional. The `staleness.json` file is generated by `osoji check` and
is useful to commit for CI visibility.

### The `rules` file

If the audit produces false positives, create a `.osoji/rules` file with
plain-text overrides:

```
Keep CLAUDE_CODE_PROMPT.md as historical reference.
Files in docs/internal/ are team documentation, not debris.
```

These rules are read by the audit pipeline and applied during debris
classification. Rules use natural language -- the LLM interprets them
during analysis.

---

## Step 7: Configuring providers via TOML

For lower-friction usage, configure default providers and model tiers in TOML
files instead of passing flags on every command.

**Global defaults** (`~/.config/osoji/config.toml`):

```bash
mkdir -p ~/.config/osoji
cat > ~/.config/osoji/config.toml <<'EOF'
default_provider = "openai"

[providers.openai]
small = "gpt-5-mini"
medium = "gpt-5.2"
large = "gpt-5.4"
EOF
```

**Per-project override** (`.osoji.local.toml`, add to `.gitignore`):

```bash
cat > .osoji.local.toml <<'EOF'
default_provider = "openai"

[providers.openai]
medium = "gpt-5.4"
EOF
```

Environment variables still override TOML when needed:

```bash
export OSOJI_PROVIDER=openai
export OSOJI_MODEL_MEDIUM=gpt-5.4
```

---

## Wrap-up

In this tutorial you have:

1. **Installed Osoji** via pip or pipx and verified the `osoji` CLI is
   available.
2. **Generated shadow documentation** for a project, creating the `.osoji/`
   directory with per-file summaries, facts, symbols, and findings.
3. **Run a documentation audit** and read the scorecard covering
   documentation coverage, accuracy, dead docs, and code junk metrics.
4. **Explored the full command surface** including diff analysis, safety
   checks, statistics, git hooks, configuration inspection, skill files,
   observatory export, and push.

### Next steps

- **Generating Shadow Documentation** (tutorial) -- Deeper dive into
  shadow doc generation, staleness, caching, and the `.osoji/` directory
  layout.
- **Running Your First Documentation Audit** (tutorial) -- Detailed
  walkthrough of audit phases, scorecard interpretation, and acting on
  findings.
- **Protecting Your Repository with Safety Checks** (tutorial) --
  Hands-on guide to setting up personal path and secret detection with git
  hooks.
- **Using Doc Prompts to Fill Documentation Gaps** (tutorial) --
  Concept-centric coverage analysis and writing prompt generation.

---

## Quick reference

| Command | Purpose |
|---------|---------|
| `osoji shadow .` | Generate shadow documentation |
| `osoji shadow --dry-run .` | Preview what would be generated |
| `osoji shadow --force .` | Regenerate everything |
| `osoji check .` | Check for stale/missing shadow docs |
| `osoji check --dry-run .` | Read-only staleness report |
| `osoji audit .` | Run documentation audit |
| `osoji audit . --full` | Run all optional audit phases |
| `osoji audit . --format html` | Generate HTML report |
| `osoji audit . --format json` | Generate JSON report |
| `osoji report .` | Re-render last audit result |
| `osoji diff` | Documentation impact of changes |
| `osoji stats .` | Token statistics |
| `osoji safety check` | Check staged files for paths/secrets |
| `osoji safety patterns` | Show detection patterns |
| `osoji safety self-test` | Self-verify Osoji package |
| `osoji hooks install` | Install git hooks |
| `osoji hooks uninstall` | Remove git hooks |
| `osoji config show .` | Show resolved configuration |
| `osoji skills list` | List available AI skills |
| `osoji skills show NAME` | Display a skill's content |
| `osoji export .` | Export observatory bundle |
| `osoji push` | Push bundle to osoji-teams |
