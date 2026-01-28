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

Run a documentation audit to detect debris (process artifacts that shouldn't be maintained):

```bash
docstar audit /path/to/project

# Skip auto-fixing shadow docs
docstar audit /path/to/project --no-fix
```

The audit checks for:
- **Debris**: Process artifacts like implementation prompts, scratch notes, or one-time guides
- **Stale shadow docs**: Auto-fixed by default

Override debris detection with project-specific rules in `.docstar/rules`:
```
Keep CLAUDE_CODE_PROMPT.md as historical reference.
Files in docs/internal/ are team documentation, not debris.
```

### Git Hooks for Automatic Updates

Install git hooks to enforce documentation quality:

```bash
# Install hooks (pre-commit + pre-push by default)
docstar hooks install

# Install with options
docstar hooks install --no-pre-commit --pre-push

# Remove hooks
docstar hooks uninstall
```

**Installed hooks:**
- `pre-commit`: Runs documentation audit and blocks commits if debris is found
- `pre-push`: Warns about stale shadow docs before push
- `post-commit` (optional): Reminds to update after commit

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
5. **Git integration**: Hooks keep docs synchronized with code changes

## Rate Limits

Docstar respects Anthropic API rate limits automatically. Override defaults via environment variables:

```bash
export ANTHROPIC_RPM=4000          # Requests per minute
export ANTHROPIC_INPUT_TPM=2000000  # Input tokens per minute
export ANTHROPIC_OUTPUT_TPM=400000  # Output tokens per minute
```
