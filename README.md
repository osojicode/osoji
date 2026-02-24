# Docstar - Shadow Documentation Engine

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

Set your Anthropic API key in your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
export ANTHROPIC_API_KEY=your-api-key
```

This ensures the key is available for both CLI usage and git hooks.

### Generate Shadow Documentation

```bash
docstar shadow /path/to/project
```

Force regeneration of all files (ignore cached hashes):

```bash
docstar shadow /path/to/project --force
```

### Check for Stale Documentation

```bash
docstar check /path/to/project
```

### View Token Statistics

See how much compression shadow docs provide:

```bash
docstar stats /path/to/project

# With per-file breakdown
docstar stats /path/to/project --verbose
```

Sample output:
```
============================================================
DOCSTAR TOKEN STATISTICS
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
docstar audit /path/to/project

# Skip auto-fixing shadow docs
docstar audit /path/to/project --no-fix

# Also detect cross-file dead code
docstar audit /path/to/project --dead-code

# Detect unactuated config/schema obligations
docstar audit /path/to/project --dead-plumbing

# Run all optional phases
docstar audit /path/to/project --full
```

The audit checks for:
- **Documentation classification**: Categorizes each doc via the Diataxis framework, flagging process artifacts (debris) as errors
- **Accuracy validation**: Matches docs to relevant source code (via explicit references and semantic topic matching), then validates accuracy against shadow docs with evidence quotes
- **Code debris**: Surfaces findings from shadow generation (stale comments, misleading docstrings, dead code) stored in `.docstar/findings/`
- **Stale shadow docs**: Auto-fixed by default
- **Cross-file dead code** (opt-in with `--dead-code`): Detects unused symbols across the codebase
- **Dead plumbing** (opt-in with `--dead-plumbing`): Detects unactuated config/schema obligations

Override findings with project-specific rules in `.docstar/rules`:
```
Keep CLAUDE_CODE_PROMPT.md as historical reference.
Files in docs/internal/ are team documentation, not debris.
```

### Documentation Diff

Show documentation impact of source changes against a git ref:

```bash
docstar diff                    # Compare against main
docstar diff develop            # Compare against develop
docstar diff HEAD~5             # Compare against 5 commits ago
docstar diff main --update      # Also regenerate stale shadows
docstar diff main --format json # Machine-readable output
```

### Safety Checks

Scan files for personal paths and secrets before committing:

```bash
docstar safety check              # Check staged files
docstar safety check src/*.py     # Check specific files
docstar safety patterns           # Show detection patterns
docstar safety self-test          # Verify docstar package itself
```

Install `detect-secrets` for secret detection: `pip install 'docstar[safety]'`

### Git Hooks for Automatic Updates

Install git hooks to enforce documentation quality:

```bash
# Install hooks (pre-commit + pre-push by default)
docstar hooks install

# Selective hook installation
docstar hooks install --no-pre-push            # pre-commit only
docstar hooks install --no-pre-commit --post-commit  # post-commit only

# Remove hooks
docstar hooks uninstall
```

**Installed hooks:**
- `pre-commit` (default: on): Runs safety check and documentation audit, blocking commits if either fails
- `pre-push` (default: on): Warns about stale shadow docs before push
- `post-commit` (default: off): Reminds to update after commit

## Output

Shadow documentation is written to `.docstar/shadow/` in the target directory, mirroring the source structure with `.shadow.md` extensions.

Each shadow doc contains:
- Source file path and hash for staleness detection
- Generation timestamp
- Semantically dense summary of the file's purpose, structure, and key details

## How It Works

1. **Bottom-up traversal**: Processes deepest files first, then rolls up to directories
2. **Tool-forced output**: LLM must call structured tools - no text parsing required
3. **Incremental updates**: Skips unchanged files by comparing source hashes
4. **Line number preprocessing**: Provides line context to the LLM for precise references
5. **Multi-model pipeline**: Shadow generation uses Sonnet. Audit uses Haiku for fast topic matching, Opus for classification and validation, and Sonnet for error-finding verification.
6. **Git integration**: Hooks keep docs synchronized with code changes

## Rate Limits

Docstar respects Anthropic API rate limits automatically. Override defaults via environment variables:

```bash
export ANTHROPIC_RPM=4000          # Requests per minute
export ANTHROPIC_INPUT_TPM=2000000  # Input tokens per minute
export ANTHROPIC_OUTPUT_TPM=400000  # Output tokens per minute
export ANTHROPIC_TPM=1000000       # Set both input and output TPM (legacy; INPUT_TPM/OUTPUT_TPM take precedence)
```
