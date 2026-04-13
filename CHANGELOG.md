# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-03-23

### Added

- `osoji audit` — multi-phase codebase audit with documentation classification,
  accuracy validation, and code debris detection
- Optional audit phases: `--dead-code`, `--dead-params`, `--dead-plumbing`,
  `--dead-deps`, `--dead-cicd`, `--orphaned-files` (or `--junk` for all)
- `--obligations` — cross-file implicit string contract detection
- `--doc-prompts` — concept-centric documentation coverage and writing prompts
- `--full` — run all optional phases at once
- `osoji shadow` — shadow documentation generation with incremental updates
- `osoji check` — staleness checking with `--dry-run` mode
- `osoji diff` — git diff documentation impact analysis
- `osoji stats` — token compression statistics
- `osoji report` — re-render audit results in text, JSON, or HTML
- `osoji export` — stable observatory bundle export (JSON Schema Draft 2020-12)
- `osoji push` — push observatory bundle to osoji-teams ingest API
- `osoji hooks install/uninstall` — git hook management (pre-commit, pre-push,
  post-commit)
- `osoji safety check/self-test/patterns` — personal path and secret scanning
- `osoji config show` — display resolved configuration
- `osoji skills list/show` — bundled AI agent skill files (`osoji-sweep`,
  `osoji-triage`)
- Multi-provider LLM support: Anthropic, OpenAI, Google Gemini, OpenRouter
  (all via LiteLLM), Claude Code (via CLI subprocess)
- Tiered model configuration (small / medium / large) via TOML config files
- Reservation-based async rate limiter with provider-specific defaults and
  environment variable overrides
- Python and TypeScript AST extraction plugins (`src/osoji/plugins/`)
- Statistical prompt regression test framework with binomial hypothesis testing
- Observatory JSON Schema (Draft 2020-12) for bundle validation

[0.2.0]: https://github.com/osojicode/osoji/releases/tag/v0.2.0
