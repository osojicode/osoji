# Docstar - Shadow Documentation Engine

Generates "shadow documentation" - semantically dense summaries of codebases optimized for AI agent consumption.

## Installation

```bash
pip install -e .
```

## Usage

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your-api-key
```

Generate shadow documentation for a codebase:

```bash
docstar shadow /path/to/project
```

Force regeneration of all files (ignore cached hashes):

```bash
docstar shadow /path/to/project --force
```

Check for stale or missing shadow documentation:

```bash
docstar check /path/to/project
```

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
