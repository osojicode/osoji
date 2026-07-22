# src\osoji\safety\paths.py
@source-hash: 1b2ad52f15f72075
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:16Z

## Purpose
Detects personal filesystem paths in source files using compiled regex patterns. Used to prevent accidental commitment of personal paths (home directories, cloud storage paths, dated project folders, etc.) to version control.

## Key Components

### Module-Level Constants

**`PATTERNS` (L20–55)** — `dict[str, re.Pattern[str]]`
Six compiled regex patterns keyed by descriptive name. All compiled once at module load for performance:
- `windows_user` (L24–26): `C:\Users\<name>\` — excludes `test/`, `user/`, `example/`, `runner/`
- `unix_home` (L30–32): `/home/<name>/` or `/Users/<name>/` — excludes `test/`, `user/`, `example/`, `runner/`, `ubuntu/`
- `cloud_storage` (L36–39): Dropbox, OneDrive, Google Drive, iCloud, Box, pCloud — case-insensitive
- `dated_folder` (L43): `/<6-digits> UPPERCASE/` format
- `personal_folder` (L47–50): Documents, Desktop, Downloads, Pictures, Videos — case-insensitive
- `my_folder` (L54): `/My <word>/` pattern — case-insensitive

**`PATTERN_DESCRIPTIONS` (L58–65)** — `dict[str, str]`
Human-readable strings corresponding to each pattern key in `PATTERNS`. Returned by `get_pattern_descriptions()`.

### Functions

**`check_file_for_paths(file_path: Path) -> list[PathFinding]` (L68–83)**
Public entry point. Reads file as UTF-8 with `errors="replace"`, returns `[]` on `OSError`. Delegates scanning to `_scan_content`.

**`_scan_content(content: str, file_path: Path) -> list[PathFinding]` (L86–112)**
Internal. Splits content on `\n`, iterates lines × patterns, collects all regex matches. Creates `PathFinding` per match with `file`, `line_number`, `line_content` (stripped), `pattern_name`, and `match` (raw match group).

**`get_pattern_descriptions() -> dict[str, str]` (L115–121)**
Returns a shallow copy of `PATTERN_DESCRIPTIONS`. Safe for external mutation.

**`self_test() -> tuple[bool, list[PathFinding]]` (L124–159)**
Runs `check_file_for_paths` against `__file__` (this module's own source). Filters out findings from comment lines (`#`), list items (`-`), documentation keywords (`Catches:`, `Excludes:`, `e.g.,`), lines containing `example`, and lines with known pattern description substrings (`home/username`, `Users/username`, `"unix_home":`, `"windows_user":`). Returns `(True, [])` if no real personal paths found.

## Dependencies
- `re` (stdlib): Regex compilation and matching
- `pathlib.Path` (stdlib): File reading and `__file__` resolution
- `.models.PathFinding`: Data class/model for findings — fields used: `file`, `line_number`, `line_content`, `pattern_name`, `match`

## Architectural Notes
- Patterns are module-level singletons (compiled once) — callers should import and reuse, not recompile.
- `self_test()` uses heuristic filtering, not a whitelist; false negatives are possible if new documentation example patterns are added.
- `_scan_content` is a pure function (no I/O), testable independently from `check_file_for_paths`.
- `check_file_for_paths` silently swallows all `OSError` variants — callers receive no signal about unreadable files beyond an empty list.

## Critical Constraints
- `windows_user` and `unix_home` exclusion lists are hardcoded (L25, L31). Adding new CI runner usernames requires modifying the regex directly.
- `dated_folder` requires exactly 6 digits + space + ALL-UPPERCASE letters (L43). Mixed-case project names are not caught.
- `self_test()` filter at L157 only skips lines containing `"unix_home":` or `"windows_user":` — if new pattern names are added whose descriptions contain real path fragments, `self_test()` may report false positives.