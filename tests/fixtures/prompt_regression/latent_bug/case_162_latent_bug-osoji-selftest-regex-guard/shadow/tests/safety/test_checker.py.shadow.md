# tests\safety\test_checker.py
@source-hash: a66a2f4fe081ffad
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:47Z

## Purpose
Test suite for the `osoji.safety.checker` orchestrator module. Validates the behavior of `check_file`, `check_files`, and `format_check_result` functions, as well as `CheckResult` and `PathFinding` data models from `osoji.safety.models`.

## Test Classes

### `TestCheckFile` (L13–69)
Tests the `check_file(path: Path) -> CheckResult` function:
- **`test_finds_personal_path`** (L16–25): Writes a file with a Unix personal path (`/home/jsmith/projects`) and asserts `result.passed == False`, 1 path finding, 1 file checked.
- **`test_safe_file_passes`** (L27–36): Clean Python content passes with 0 findings, 1 file checked.
- **`test_skips_binary_file`** (L38–47): PNG bytes cause `files_checked == 0`, `files_skipped == 1`, result passes.
- **`test_handles_nonexistent_file`** (L49–54): Missing file → `files_checked == 0`, 1 error entry.
- **`test_multiple_findings_in_file`** (L56–69): File with Unix and Windows personal paths produces 2 findings.

### `TestCheckFiles` (L72–110)
Tests the `check_files(paths: list[Path]) -> CheckResult` function:
- **`test_checks_multiple_files`** (L75–82): Two files → `files_checked == 2`.
- **`test_aggregates_findings`** (L84–92): Two files each with 1 finding → 2 total path findings.
- **`test_filters_binary_files`** (L94–102): Mixed list → 1 checked, 1 skipped.
- **`test_empty_list`** (L104–109): Empty input → passed, `files_checked == 0`.

### `TestCheckResult` (L112–190)
Tests the `CheckResult` dataclass directly:
- **`test_passed_when_empty`** (L115–119): Default-constructed `CheckResult()` should pass.
- **`test_not_passed_with_path_findings`** (L121–132): Any path finding → `passed == False`.
- **`test_finding_count`** (L134–155): `finding_count` property counts path findings (2 expected).
- **`test_merge_combines_results`** (L157–165): `r1.merge(r2)` sums `files_checked` and `files_skipped`.
- **`test_summary_passed`** (L167–172): Summary string includes `"passed"` and the file count.
- **`test_summary_failed`** (L174–190): Summary includes `"failed"` and finding count.

### `TestFormatCheckResult` (L193–254)
Tests the `format_check_result(result, verbose=False) -> str` function:
- **`test_format_passed`** (L196–203): Output includes `"passed"` and `"no issues"`.
- **`test_format_failed_with_paths`** (L205–225): Output contains `"FAILED"`, filename `"config.py"`, line number `"15"`, and pattern name `"unix_home"`.
- **`test_verbose_includes_counts`** (L227–234): `verbose=True` includes file checked and skipped counts.
- **`test_includes_remediation_suggestions`** (L236–254): Failed output contains remediation text (`"Replace personal paths"` or `"generic alternatives"`) and `"--no-verify"` emergency bypass flag.

## Key Dependencies
- **`osoji.safety.checker`**: Provides `check_file`, `check_files`, `format_check_result` — the system under test.
- **`osoji.safety.models`**: Provides `CheckResult` (dataclass with `passed`, `path_findings`, `files_checked`, `files_skipped`, `errors`, `finding_count`, `merge()`, `summary()`) and `PathFinding` (fields: `file`, `line_number`, `line_content`, `pattern_name`, `match`).
- **`temp_dir` fixture** (L16, L27, L38, L49, L56, L75, L84, L94, L205): Pytest fixture (not defined in this file — likely in `conftest.py`) providing a temporary `Path` directory.
- **`pathlib.Path`** (L3): Used directly in `PathFinding` construction.

## Patterns / Architecture
- Standard pytest class-based grouping by function under test.
- Uses `temp_dir` pytest fixture for filesystem tests (write real files, verify detection logic).
- Direct model instantiation (`CheckResult`, `PathFinding`) for unit tests that bypass the file I/O layer.
- Personal path test data: Unix (`/home/jsmith/...`, `/home/alice/...`, `/home/user/...`) and Windows (`C:\Users\alice\docs`) patterns.
- `format_check_result` is tested for both content correctness and presence of a CLI bypass hint (`--no-verify`).

## Implicit Contracts Revealed
- `CheckResult.passed` must be `False` when `path_findings` is non-empty.
- `CheckResult.files_skipped` must be incremented for binary files, not `files_checked`.
- `CheckResult.errors` must receive an entry for unreadable/non-existent files.
- `format_check_result` must emit `"FAILED"` (uppercase) in output for failures.
- `format_check_result` must emit remediation text and `--no-verify` for failures.