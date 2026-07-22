# pyproject.toml
@source-hash: ee6331a4e13a1585
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:14Z

## Project Configuration: `pyproject.toml`

### Identity (L5-8)
- **Package name**: `osojicode` (PyPI distribution name)
- **Import name**: `osoji` (from `src/osoji`, see L63)
- **Version**: `0.2.0` (L7)
- **Description**: Shadow documentation engine — generates semantically dense summaries of codebases for AI agent consumption (L8)

### Entry Point (L47-48)
- CLI command `osoji` maps to `osoji.cli:main`

### Build System (L1-3)
- Uses **hatchling** as build backend
- Source layout: `src/osoji` (L63) — standard `src/` layout

### Runtime Dependencies (L30-40)
| Package | Version Floor | Notes |
|---|---|---|
| `anthropic` | >=0.39.0 | Anthropic/Claude LLM API client |
| `click` | >=8.3.3 | CLI framework; floor excludes PYSEC-2026-2132 (command injection in `click.edit`) |
| `google-genai` | >=1.10.0 | Google Gemini LLM API client |
| `openai` | >=1.75.0 | OpenAI LLM API client |
| `pyasn1` | >=0.6.4 | Transitive via `google-auth`; floor excludes CVE-2026-59885/59886 |
| `python-dotenv` | >=1.0.0 | `.env` file loading |
| `tabulate` | >=0.9.0 | Table formatting for output |
| `tree-sitter` | >=0.25,<0.27 | AST parsing (upper-bounded for API stability) |
| `tree-sitter-python` | >=0.23.6 | Python grammar for tree-sitter |

### Optional Dependency Groups (L42-45)
- **`safety`**: `detect-secrets>=1.4.0` — secret scanning
- **`all`**: same as `safety` (mirrors `safety` group)
- **`dev`**: `pytest`, `pytest-mock`, `pytest-asyncio`, `scipy`, `jsonschema`, `claude-agent-sdk>=0.2.110` — test and evaluation tooling

### Python Version Support (L10, L23-25)
- Requires Python >=3.11; classifiers cover 3.11, 3.12, 3.13

### Test Configuration (L50-60)
- `asyncio_mode = "strict"` — all async tests must be explicitly marked
- `asyncio_default_fixture_loop_scope = "function"` — per-test event loops
- `--ignore=tests/fixtures` — fixture corpora excluded from collection (they pin a snapshot's API, not the live package's)
- Custom markers:
  - `prompt_regression` — live LLM API calls for prompt behavior verification
  - `live_smoke` — optional live provider smoke tests
  - `corpus_evaluate` — opt-in V1-7 corpus evaluator (live LLM calls, via `pytest --evaluate`)

### Project URLs (L65-68)
- Homepage/Repository: `https://github.com/osojicode/osoji`
- Issues: `https://github.com/osojicode/osoji/issues`
- Changelog: `CHANGELOG.md` on `main` branch

### Architectural Notes
- Three LLM provider clients (`anthropic`, `openai`, `google-genai`) are all hard runtime dependencies, suggesting multi-provider support is core functionality, not optional
- `tree-sitter` upper-bounded at `<0.27` — agents should be aware of API compatibility constraint
- `detect-secrets` is optional (`safety`/`all` extras) — secret scanning is an opt-in feature
- The `all` extra only includes `detect-secrets`, not dev tools — install `dev` separately for testing