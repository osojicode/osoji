# tests\safety\test_cli.py
@source-hash: 1ad595faf8a68176
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:37Z

## Purpose
Integration/CLI tests for the `osoji safety` command group using Click's `CliRunner`. Validates the `check`, `patterns`, `self-test`, and `--help` subcommands via subprocess-style invocation.

## Structure Overview

### Fixture
- **`runner` (L10-13)**: Returns a `CliRunner()` instance for invoking Click commands in isolation.
- **`temp_dir`** (used at L21, L31, L41, etc.): Session- or module-level fixture assumed to come from `conftest.py` (not defined here).

### Test Classes

#### `TestSafetyCheck` (L16-58)
Tests for `osoji safety check <file(s)>`:
- **`test_check_clean_file` (L19-27)**: Writes `print("hello")` to a temp file, expects exit code 0 and "passed" in output.
- **`test_check_finds_personal_path` (L29-37)**: Writes a Windows-style user path (`C:\Users\jsmith\data`) to a temp file, expects exit code 1 and "FAILED" in output.
- **`test_check_multiple_files` (L39-48)**: Invokes check with two clean files, expects exit code 0.
- **`test_check_verbose_output` (L50-58)**: Invokes with `-v` flag before `safety check`, expects exit code 0 and "Files checked" in output.

#### `TestSafetyPatterns` (L61-95)
Tests for `osoji safety patterns`:
- **`test_patterns_shows_all_patterns` (L64-74)**: Asserts six specific pattern names appear in output: `windows_user`, `unix_home`, `cloud_storage`, `dated_folder`, `personal_folder`, `my_folder`.
- **`test_patterns_shows_regex` (L76-81)**: Asserts `"Regex:"` appears in output.
- **`test_patterns_shows_count` (L83-88)**: Asserts `f"Total: {len(PATTERNS)} patterns"` appears — directly references `PATTERNS` from `osoji.safety.paths` to compute expected count.
- **`test_patterns_shows_secrets_status` (L90-95)**: Asserts `"detect-secrets"` appears in output.

#### `TestSafetySelfTest` (L98-113)
Tests for `osoji safety self-test`:
- **`test_self_test_passes` (L101-106)**: Asserts exit code 0 and "passed" in output — implicitly validates that the osoji package itself is clean.
- **`test_self_test_scans_package` (L108-113)**: Asserts either "Scanning" or "osoji" appears in output.

#### `TestSafetyHelp` (L116-133)
Tests for help text rendering:
- **`test_safety_group_help` (L119-126)**: Asserts `check`, `self-test`, and `patterns` appear in `osoji safety --help` output.
- **`test_safety_check_help` (L128-133)**: Asserts FILES argument mention in `osoji safety check --help`.

## Key Dependencies
- `osoji.cli.main`: Root Click group entrypoint; invoked with full CLI argument strings.
- `osoji.safety.paths.PATTERNS`: Imported to derive expected pattern count in `test_patterns_shows_count`.
- `click.testing.CliRunner`: Used for all command invocations; captures stdout/exit codes.
- `temp_dir` fixture: Must be defined in `conftest.py`; provides a `pathlib.Path` writable temp directory.

## Architectural Notes
- All CLI invocations follow the pattern `runner.invoke(main, [subcommand, ...args])`.
- The `-v` verbose flag is placed before the subcommand (`["-v", "safety", "check", ...]`), indicating it is a flag on the root `main` group, not on `safety check`.
- Tests use string matching on `result.output` rather than structured output parsing.
- `test_self_test_passes` depends on the actual osoji package being free of personal paths at test time — environment-sensitive.
