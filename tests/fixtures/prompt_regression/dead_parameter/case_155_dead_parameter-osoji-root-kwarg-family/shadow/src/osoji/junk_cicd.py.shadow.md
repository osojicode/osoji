# src\osoji\junk_cicd.py
@source-hash: b6e9f5f7104725e9
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:04Z

## Dead CI/CD Detection Module

Detects stale/dead CI/CD pipeline elements by parsing configuration files, identifying referenced paths that no longer exist in the repo, and using LLM-based triage to confirm staleness.

### Architecture Overview

**Pipeline:** `discover_cicd_files` → parse (regex or LLM) → `_check_path_references` → `_build_candidates` → `finding_from_cicd_candidate` → `build_junk_claims` / `decide_junk_claims` → `JunkAnalysisResult`

### Core Data Classes

- **`CICDElement` (L25-36):** Raw parsed element from a CI/CD file. Fields: `cicd_file`, `element_type`, `element_name`, `line_start`, `line_end`, `referenced_paths`, `referenced_commands`, `missing_paths` (populated post-check).
- **`CICDCandidate` (L39-50):** Element narrowed to have missing path references. Adds `element_content` (raw text slice) and `full_file_content` for LLM context.

### Key Functions

- **`discover_cicd_files(config)` (L54-103):** Scans repo root for CI/CD files across 7 CI systems: GitHub Actions (`.github/workflows/*.yml`), Makefile variants, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/config.yml`, `azure-pipelines.yml`, `.travis.yml`. Returns `list[tuple[Path, str]]`. Bypasses `list_repo_files()` for `.github/` (excluded by default ignore patterns).

- **`_parse_github_workflow(content, path)` (L108-193):** Regex-based parser for GitHub Actions YAML. Extracts jobs at 2-space indent under `jobs:`, handles `run:` (inline and multiline `|` blocks) and `uses:` steps. Returns `list[CICDElement]`.

- **`_parse_makefile(content, path)` (L196-238):** Extracts Makefile targets matching `[a-zA-Z_][\w.\-]*:`, with tab-indented recipe commands. Uses `_flush()` inner function to emit elements on target boundary.

- **`_parse_gitlab_ci(content, path)` (L241-298):** Extracts top-level keys not in a hardcoded `reserved_keys` set (L246-253) as GitLab jobs. Extracts `script:` block commands.

- **`_parse_cicd_via_llm(provider, content, path, cicd_type, config)` (L312-355):** Async fallback parser for unsupported CI types (Jenkinsfile, CircleCI, Azure, Travis). Uses small LLM model with `extract_cicd_elements` tool call. Returns `(elements, input_tokens, output_tokens)`.

- **`_extract_paths_from_command(command)` (L373-416):** Tokenizes shell commands, strips shell variable substitutions, skips flags/URLs/common commands (`_COMMON_COMMANDS` set L361-370), returns tokens containing `/` or `.` with alphabetic chars.

- **`_check_path_references(config, elements)` (L421-468):** Builds set of known repo files via `list_repo_files` + `.github/` rglob scan. Also constructs parent directory set. Marks `element.missing_paths` for any referenced path not found in files or dirs (handles glob prefix stripping).

- **`_build_candidates(elements, file_contents)` (L471-498):** Filters elements with non-empty `missing_paths`, slices `element_content` from file, returns `list[CICDCandidate]`.

- **`detect_dead_cicd_async(provider, config, on_progress, cicd_files)` (L510-594):** Main async pipeline. Discovers files, parses with regex (`_CICD_PARSERS` dict L503-507) or LLM fallback, checks paths, builds candidates, routes through `finding_from_cicd_candidate` → `build_junk_claims` → `decide_junk_claims`. Returns `(decided_findings, total_candidates)`. All verdicts returned; callers filter for `"confirmed"`.

### `DeadCICDAnalyzer` Class (L597-659)

Implements `JunkAnalyzer` interface:
- `name` = `"dead_cicd"`, `cli_flag` = `"dead-cicd"`
- `analyze(config)` (L612-628): Sync entry — pre-checks CI/CD files, then runs `asyncio.run(_run())` with a `create_runtime`-supplied provider.
- `analyze_async(provider, config, on_progress, cicd_files)` (L630-659): Filters `decided` findings to `verdict == "confirmed"`, maps to `JunkFinding` objects using `_scanner_meta` for `element_name`/`element_type`. Uses `f.confidence` with `0.0` default, `f.triage_reasoning` for reason, `f.suggested_fix` or generated remediation string.

### Parser Registry

`_CICD_PARSERS` (L503-507): Maps `"github_workflow"`, `"makefile"`, `"gitlab_ci"` to regex parsers. All other types fall back to LLM parsing.

### LLM System Prompt

`_EXTRACT_CICD_SYSTEM_PROMPT` (L301-309): Instructs LLM to extract all pipeline elements with name, type, line range, referenced paths, and commands.

### Notable Design Decisions

- `.github/` is explicitly excluded from `list_repo_files()` (per default ignore patterns), so both `discover_cicd_files` and `_check_path_references` use `iterdir()`/`rglob()` directly.
- Missing paths are the primary (but not dispositive) staleness signal — triage LLM also considers external targets, dynamic discovery, and phony targets.
- Token counts from LLM parsing are discarded (`_in_tok`, `_out_tok` at L555, L591).
