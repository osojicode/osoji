# osoji

**The garbage collector for your codebase**

[![PyPI version](https://img.shields.io/pypi/v/osojicode)](https://pypi.org/project/osojicode/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/osojicode)](https://pypi.org/project/osojicode/)
[![License](https://img.shields.io/github/license/osojicode/osoji)](https://github.com/osojicode/osoji/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/osojicode/osoji/ci.yml)](https://github.com/osojicode/osoji/actions/workflows/ci.yml)

## What it does

osoji audits your codebase for dead code, stale documentation, misleading comments, and semantic contradictions. It produces structured, actionable findings — and ships with agent skill files that automate the entire triage-fix-feedback loop. Stop wasting time working around the garbage accumulating in your project.

## Quick start

```bash
pip install osojicode
export ANTHROPIC_API_KEY=your-key-here
osoji audit .
```

BYOK — you pay your LLM provider directly. No data leaves your machine except API calls.

## Agent workflow

osoji ships with bundled skill files that teach AI coding agents how to work with audit findings end-to-end:

1. **Audit** — `osoji audit .` scans your codebase
2. **Triage** — your agent classifies each finding as true positive, false positive, or informational
3. **Fix** — your agent applies fixes for confirmed issues and runs tests
4. **Improve** — your agent files GitHub issues on osoji for false positives and missed detections, improving detection for everyone

### Running the skills

**Claude Code** (slash commands):

```
/osoji-sweep          # Full end-to-end: audit, triage, fix, file issues
/osoji-triage         # Read-only triage: classify findings, produce report
```

**Other agents** — pipe skill content into your agent's prompt:

```bash
osoji skills show osoji-sweep | pbcopy    # macOS
osoji skills show osoji-sweep | clip      # Windows
osoji skills list                         # See all available skills
```

### Bundled skills

- **osoji-sweep** — Audit, triage every finding, fix true positives, file GitHub issues for pipeline improvements
- **osoji-triage** — Classify findings and produce a structured report without modifying any files

### Improving detection

osoji gets smarter the more people use it. When your agent finds a false positive or spots something osoji missed, the skill files help it file a structured issue automatically. Those issues improve detection for everyone — including you on your next audit.

## What it finds

- **Dead symbols** — unused exports, unreachable code
- **Dead parameters** — function args never passed by any caller
- **Stale documentation** — docs that drifted from the code they describe
- **Misleading comments** — outdated comments, inaccurate docstrings
- **Latent bugs** — unchecked returns, type confusion patterns
- **Obligation violations** — implicit string contracts broken across files
- **Unactuated config** — config fields declared but never enforced
- **Unused dependencies** — packages listed but never imported
- **Dead CI/CD** — stale pipeline jobs, unused Makefile targets
- **Orphaned files** — source files unreachable from any entry point

## How it works

osoji generates shadow documentation to build a semantic model of your codebase, then compares that model against existing documentation and code structure. It uses tiered LLM analysis — cheap models for filtering, expensive models for deep verification — and produces structured JSON findings that agents and humans can act on. Analysis is semantic, not purely AST-based, so it works on any language. AST plugins can augment detection for supported languages (Python, TypeScript).

## Commands

| Command | Description |
|---------|-------------|
| `osoji audit .` | Scan for dead code, stale docs, and semantic issues |
| `osoji shadow .` | Generate shadow documentation |
| `osoji check .` | Check for stale or missing shadow docs |
| `osoji diff` | Show documentation impact of source changes |
| `osoji stats .` | Token statistics for source vs shadow docs |
| `osoji report .` | Re-render last audit in a different format |
| `osoji export .` | Export observatory bundle |
| `osoji push` | Push bundle to osoji-teams |
| `osoji skills list` | List bundled agent skill files |
| `osoji config show` | Inspect resolved configuration |
| `osoji hooks install` | Manage git hooks |
| `osoji safety check` | Pre-commit safety checks |

Use `osoji <command> --help` for full options.

## Configuration

osoji is BYOK — bring your own key. It defaults to Anthropic but supports OpenAI, Google, and OpenRouter.

Set your API key and go:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Switch providers per command:

```bash
osoji audit . --provider openai --model gpt-5.2
osoji audit . --provider google --model gemini-2.0-flash
```

Or configure defaults in TOML:

```toml
# ~/.config/osoji/config.toml (global)
# .osoji.local.toml (per-project, gitignored)

default_provider = "openai"

[providers.openai]
small = "gpt-5-mini"
medium = "gpt-5.2"
large = "gpt-5.4"
```

Supported provider credentials: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`

Config precedence (highest to lowest):

1. CLI flags (`--provider`, `--model`)
2. Environment variables (`OSOJI_PROVIDER`, `OSOJI_MODEL`)
3. `.osoji.local.toml` (per-project)
4. `~/.config/osoji/config.toml` (global)
5. Built-in defaults

Run `osoji config show` to inspect the effective policy.

## Requirements

- Python 3.11+
- An LLM API key (Anthropic recommended, OpenAI and Google also supported)

## Links

- Website: [osojicode.ai](https://osojicode.ai)
- PyPI: [pypi.org/project/osojicode](https://pypi.org/project/osojicode/)
- Issues: [github.com/osojicode/osoji/issues](https://github.com/osojicode/osoji/issues)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and
contribution guidelines.

## Security

To report security vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) for the full text.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
