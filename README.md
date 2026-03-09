# Osoji - Shadow Documentation Engine

Generates "shadow documentation" - semantically dense summaries of codebases optimized for AI agent consumption.

## Installation

Using pipx (recommended for CLI tools):
```bash
pipx install -e .
```

Or with pip:
```bash
pip install -e .
```

## Usage

Osoji defaults to `anthropic`, but `shadow`, `audit`, `stats`, and `diff --update` can all switch providers with `--provider` and `--model`.

Configure Anthropic as the default provider:

```bash
export ANTHROPIC_API_KEY=your-api-key
osoji shadow /path/to/project
```

Switch providers per command:

```bash
osoji shadow /path/to/project --provider openai --model gpt-5.2
osoji audit /path/to/project --provider google --model gemini-2.0-flash
osoji stats /path/to/project --provider openrouter --model openai/gpt-5-mini
```

For lower-friction defaults, configure model policy in TOML:

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

Optional per-project personal override (recommended to gitignore):

```bash
cat > /path/to/project/.osoji.local.toml <<'EOF'
default_provider = "openai"

[providers.openai]
medium = "gpt-5.4"
EOF
```

Environment variables still override TOML when needed:

```bash
export OPENAI_API_KEY=your-api-key
export OSOJI_PROVIDER=openai
export OSOJI_MODEL_MEDIUM=gpt-5.4
```

Supported provider credentials:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`

Config precedence for provider/model resolution:

1. CLI flags
2. Environment variables
3. `<project>/.osoji.local.toml`
4. `~/.config/osoji/config.toml`
5. Built-in defaults

LLM-backed commands print the resolved config trace to `stderr` by default so it is obvious when a project-local config overrides global defaults. Use `osoji config show` to inspect the effective policy directly.

### Generate Shadow Documentation

```bash
osoji shadow /path/to/project
```

Force regeneration of all files (ignore cached hashes):

```bash
osoji shadow /path/to/project --force
```

### Check for Stale Documentation

```bash
osoji check /path/to/project
```

### View Token Statistics

See how much compression shadow docs provide:

```bash
osoji stats /path/to/project

# With per-file breakdown
osoji --verbose stats /path/to/project

# Count tokens with a specific provider/model
osoji stats /path/to/project --provider openai --model gpt-5.2
```

Sample output:
```
============================================================
OSOJI TOKEN STATISTICS
============================================================

Files analyzed:      7
Files with shadows:  7

Source tokens:       1,842
Shadow tokens:         743

Compression ratio:   40.34%
Token savings:       59.7%

============================================================
```

### Documentation Audit

Run a documentation audit to classify docs and validate their accuracy against source code:

```bash
osoji audit /path/to/project

# Skip auto-fixing shadow docs
osoji audit /path/to/project --no-fix

# Run against a non-default provider/model
osoji audit /path/to/project --provider google --model gemini-2.0-flash

# Also detect cross-file dead code
osoji audit /path/to/project --dead-code

# Detect unactuated config/schema obligations
osoji audit /path/to/project --dead-plumbing

# Detect unused package dependencies
osoji audit /path/to/project --dead-deps

# Detect stale CI/CD pipeline elements
osoji audit /path/to/project --dead-cicd

# Detect orphaned source files
osoji audit /path/to/project --orphaned-files

# Check cross-file string contracts (no LLM calls)
osoji audit /path/to/project --obligations

# Run all junk analysis phases
osoji audit /path/to/project --junk

# Run all optional phases (equivalent to --junk --obligations)
osoji audit /path/to/project --full
```

The audit checks for:
- **Documentation classification**: Categorizes each doc via the Diataxis framework, flagging process artifacts (debris) as errors
- **Accuracy validation**: Matches docs to relevant source code (via explicit references and semantic topic matching), then validates accuracy against shadow docs with evidence quotes
- **Code debris**: Surfaces findings from shadow generation (stale comments, misleading docstrings, dead code) stored in `.osoji/findings/`
- **Stale shadow docs**: Auto-fixed by default
- **Cross-file dead code** (opt-in with `--dead-code`): Detects unused symbols across the codebase
- **Dead plumbing** (opt-in with `--dead-plumbing`): Detects unactuated config/schema obligations
- **Dead dependencies** (opt-in with `--dead-deps`): Detects unused package dependencies via import scanning and LLM verification
- **Dead CI/CD** (opt-in with `--dead-cicd`): Detects stale CI/CD pipeline elements (unused jobs, targets, stages)
- **Orphaned files** (opt-in with `--orphaned-files`): Detects source files unreachable from entry points via purpose graph analysis

Override findings with project-specific rules in `.osoji/rules`:
```
Keep CLAUDE_CODE_PROMPT.md as historical reference.
Files in docs/internal/ are team documentation, not debris.
```

### Interactive Codebase Visualization

Launch an interactive browser-based visualization of your codebase health:

```bash
osoji viz /path/to/project
```

Opens a local web page showing codebase structure, documentation coverage, and health metrics as an interactive graph.

### Documentation Diff

Show documentation impact of source changes against a git ref:

```bash
osoji diff                    # Compare against main
osoji diff develop            # Compare against develop
osoji diff HEAD~5             # Compare against 5 commits ago
osoji diff main --update      # Also regenerate stale shadows
osoji diff main --update --provider openai --model gpt-5.2
osoji diff main --format json # Machine-readable output
```

### Safety Checks

Scan files for personal paths and secrets before committing:

```bash
osoji safety check              # Check staged files
osoji safety check src/*.py     # Check specific files
osoji safety patterns           # Show detection patterns
osoji safety self-test          # Verify osoji package itself
```

Install `detect-secrets` for secret detection: `pip install 'osoji[safety]'`

### Git Hooks for Automatic Updates

Install git hooks to enforce documentation quality:

```bash
# Install hooks (pre-commit + pre-push by default)
osoji hooks install

# Selective hook installation
osoji hooks install --no-pre-push            # pre-commit only
osoji hooks install --no-pre-commit --post-commit  # post-commit only

# Remove hooks
osoji hooks uninstall
```

**Installed hooks:**
- `pre-commit` (default: on): Runs safety check (blocks on failure) and shadow doc staleness check (non-blocking)
- `pre-push` (default: on): Warns about stale shadow docs before push
- `post-commit` (default: off): Reminds to update after commit

## Output

Shadow documentation is written to `.osoji/shadow/` in the target directory, mirroring the source structure with `.shadow.md` extensions.

Each shadow doc contains:
- Source file path and hash for staleness detection
- Generation timestamp
- Semantically dense summary of the file's purpose, structure, and key details

## How It Works

1. **Bottom-up traversal**: Processes deepest files first, then rolls up to directories
2. **Tool-forced output**: LLM must call structured tools - no text parsing required
3. **Incremental updates**: Skips unchanged files by comparing source hashes
4. **Line number preprocessing**: Provides line context to the LLM for precise references
5. **Tiered provider runtime**: Shadow generation uses the configured medium model. Audit uses the configured small, medium, and large tiers through a shared provider runtime that supports Anthropic, OpenAI, Google Gemini, and OpenRouter.
6. **Git integration**: Hooks keep docs synchronized with code changes

## Rate Limits

Osoji applies provider-specific defaults and supports environment overrides for every provider. Use `{PROVIDER}_RPM`, `{PROVIDER}_INPUT_TPM`, `{PROVIDER}_OUTPUT_TPM`, or `{PROVIDER}_TPM` (legacy combined override).

```bash
export ANTHROPIC_RPM=4000
export ANTHROPIC_INPUT_TPM=2000000
export ANTHROPIC_OUTPUT_TPM=400000

export OPENAI_RPM=500
export OPENAI_INPUT_TPM=500000
export OPENAI_OUTPUT_TPM=500000

export GOOGLE_RPM=300
export GOOGLE_INPUT_TPM=5000000
export GOOGLE_OUTPUT_TPM=5000000

export OPENROUTER_RPM=300
export OPENROUTER_TPM=500000
export OPENROUTER_OUTPUT_TPM=350000
```
