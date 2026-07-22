# src\osoji\cli.py
@source-hash: 461b3917f690800b
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:14Z

## Overview
Click-based CLI entry point for the Osoji tool ("garbage collector for AI-assisted codebases"). Defines the `main` command group and all subcommands/subgroups: `init`, `shadow`, `check`, `diff`, `stats`, `audit`, `report`, `push`, `export`, `corpus`, `hooks`, `safety`, `config`, `skills`.

## Key Architectural Decisions
- **CLIState dataclass** (L32-36): Frozen dataclass passed via `ctx.obj` to propagate `verbose`/`quiet` flags to all subcommands. Retrieved via `_cli_state(ctx)` helper (L77-81).
- **`_build_llm_config`** (L39-57): Central factory for `Config` objects used by LLM-backed commands. Resolves path, force, gitignore, provider, model, verbosity.
- **`_configure_utf8_output`** (L60-74): Reconfigures stdout/stderr to UTF-8/replace on Windows to handle LLM-generated Unicode in findings. Called once in `main` group callback (L104).
- **`_emit_config_banner`** (L84-89): Prints LLM config resolution banner to stderr unless quiet mode; used by LLM-backed commands.
- **`_LLM_PROVIDER_CHOICE`** (L28): Module-level `click.Choice` built from `provider_names()` for consistent provider option validation.
- **Exit codes**: Commands producing errors (`audit`, `diff`, `report`, `safety check`, `safety self-test`) raise `SystemExit(1)` explicitly (not Click's default).
- **Inline import**: `EXCLUDABLE_PHASES` imported inside `audit` command (L381) to avoid circular import at module load.
- **`skills` subcommands**: Import `skills` module lazily inside command bodies (L759, L774, L778) to avoid module-load overhead.

## Commands

### `main` group (L92-108)
Click group with `--verbose`/`--quiet` flags. Calls `_configure_utf8_output()` and `load_dotenv()` before any subcommand.

### `init` (L111-132)
Sets up `.gitignore`, `.env`, `.osoji.toml`. Delegates to `run_init(root, interactive, provider)`.

### `shadow` (L135-169)
Generates shadow documentation. Supports `--dry-run` (calls `dry_run_shadow`) and normal mode (calls `generate_shadow_docs_async` via `asyncio.run`). Raises `ClickException` on `RuntimeError`.

### `check` (L172-225)
Checks for stale/missing shadow docs. `--dry-run` calls `check_shadow_docs` (read-only); normal mode calls `mark_stale_docs` (writes stale warnings and manifest). Status colors: `stale=yellow`, `missing=red`, `stale-impl=cyan`.

### `diff` (L228-287)
Compares HEAD against a base ref for documentation impact. Optionally regenerates stale shadows with `--update`. Supports `text`/`json` output. Exits with code 1 if `report.has_issues`.

### `stats` (L290-320)
Token statistics for source vs shadow docs. Delegates to `gather_stats` + `format_stats_report`.

### `audit` (L323-424)
Full audit command with many optional phases: `--dead-code`, `--dead-params`, `--dead-plumbing`, `--dead-deps`, `--dead-cicd`, `--orphaned-files`, `--junk` (all junk), `--obligations`, `--doc-prompts`, `--full` (all optionals). Supports `--exclude` (comma-separated phase names), `--incremental`, `--since REF`. Output formats: `text`, `json`, `html` (HTML written to `config.analysis_root/report.html`). Exits with code 1 if `not result.passed`.

### `report` (L427-457)
Re-renders last audit result from cache (no LLM calls). Raises `ClickException` on missing cache. Same output formats as `audit`.

### `push` (L460-482)
Pushes observatory bundle to osoji-teams API. Delegates to `run_push`. Reports `run_id` and optional `dashboard_url`.

### `export_bundle` (L485-501, registered as `export`)
Writes observatory bundle JSON to disk. Delegates to `write_observatory_bundle`.

### `corpus` group + `corpus emit` (L504-565)
Manages evaluator fixture corpus. `corpus emit` snapshots a decided finding into a corpus case stub under `_holding/`. Delegates to `resolve_dest` + `emit_case`.

### `hooks install`/`uninstall` (L574-629)
Git hook management. `install` supports `--pre-commit`, `--pre-push`, `--post-commit` flags. Both print per-hook success/fail results.

### `safety check`/`self-test`/`patterns` (L638-730)
- `check` (L641-660): Checks files or staged files for personal paths/secrets. Exits 1 on failure.
- `self-test` (L664-700): Scans the osoji package itself. Excludes `paths.py` (handled by `paths_self_test()`). Exits 1 on failure.
- `patterns` (L704-730): Lists regex patterns with descriptions. Shows `detect-secrets` availability.

### `config show` (L739-747)
Shows effective model policy for a project root via `config.format_resolution_banner()`.

### `skills list`/`show` (L756-783)
Lists or prints bundled AI agent skill files. Lazy imports from `.skills`.

## Notable Constraints
- `--verbose` and `--quiet` are mutually exclusive (enforced at L106-107).
- `--full` sets `junk=True`, `obligations=True`, `doc_prompts=True` (L375-378).
- `--since REF` implies `--incremental` semantically (per docstring), but not enforced in code — passed as `since_ref` to `run_audit`.
- HTML output always written to `config.analysis_root / "report.html"` (L415, L449).
