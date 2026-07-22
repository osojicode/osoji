# tests\safety\test_paths.py
@source-hash: fe675066038f874b
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:25Z

## Purpose
Test suite for `osoji.safety.paths` — validates personal/sensitive path detection patterns (Windows user paths, Unix home dirs, cloud storage, dated folders, personal folders, "My X" folders) and verifies no false positives on safe paths.

## Structure
All tests use a `temp_dir` pytest fixture (provided by conftest, not defined here) to create temporary files with embedded path strings, then call `check_file_for_paths()` and assert on the returned `findings` list.

### Test Classes

**`TestWindowsUserPaths` (L13–72)**
- Tests `C:\Users\<user>\` and `C:/Users/<user>/` detection via `pattern_name == "windows_user"`
- Verifies case-insensitive drive letter matching (`c:` vs `C:`) (L38–45)
- Verifies excluded usernames: `test` (L47–54), `example` (L56–63), `runner` (L65–72) — CI/generic users must not trigger findings

**`TestUnixHomePaths` (L75–117)**
- Tests `/home/<user>/` (Linux) and `/Users/<user>/` (macOS) detection via `pattern_name == "unix_home"`
- `/Users/alice/Documents` may also trigger `personal_folder` — test filters by pattern name (L95–97)
- Excluded usernames: `test` (L99–107), `ubuntu` (L109–117)

**`TestCloudStoragePaths` (L120–145)**
- Parametrized over: `Dropbox`, `OneDrive`, `Google Drive`, `iCloud`, `Box`, `pCloud` (L123–125)
- Tests `pattern_name == "cloud_storage"` via `/Users/me/<cloud>/work/` strings
- Verifies case-insensitive matching (`/dropbox/` → detected) (L137–145)

**`TestDatedFolders` (L148–179)**
- Detects 6-digit date prefix + space + UPPERCASE name pattern: `/260124 OSOJI/` (L151–159)
- Works with backslash paths: `\251007 FIXTHEDOCS\` (L161–169)
- Requires at least one uppercase letter in the name portion (L171–179) — lowercase `project` not matched

**`TestPersonalFolders` (L182–207)**
- Parametrized over: `Documents`, `Desktop`, `Downloads`, `Pictures`, `Videos` (L186–187)
- Uses `pattern_name == "personal_folder"`
- Case-insensitive: `/DOCUMENTS/` matches (L199–207)

**`TestMyFolderPatterns` (L210–241)**
- Detects `/My Projects/`, `\My Documents\`, `/MY STUFF/` via `pattern_name == "my_folder"`
- Both forward and backslash delimiters work (L223–231)
- Case-insensitive (L233–241)

**`TestNoFalsePositives` (L244–281)**
- `/usr/local/bin`, `/etc/myapp/config.yaml`, `/var/data/app` → 0 findings (L247–261)
- Relative paths (`./src/main.py`) → 0 findings (L263–270)
- URL paths (`https://example.com/Users/api`) → `<= 1` finding (soft assertion, acknowledged gray area) (L272–281)

**`TestPatternDescriptions` (L284–293)**
- Verifies `get_pattern_descriptions()` returns a dict containing every key in `PATTERNS` with non-empty values

**`TestSelfTest` (L296–312)**
- `self_test()` must return `(True, list)` — the module's own source must not contain personal paths

## Key Contracts / Invariants
- `check_file_for_paths(path)` returns a list of finding objects with `.pattern_name` and `.match` attributes
- `pattern_name` values used in assertions: `"windows_user"`, `"unix_home"`, `"cloud_storage"`, `"dated_folder"`, `"personal_folder"`, `"my_folder"`
- `PATTERNS` is a dict/mapping keyed by pattern name strings
- `get_pattern_descriptions()` returns a dict mapping pattern names to non-empty description strings
- `self_test()` returns `tuple[bool, list]`

## Dependencies
- `pytest` — test framework, parametrize decorator
- `osoji.safety.paths` — module under test: `PATTERNS`, `check_file_for_paths`, `get_pattern_descriptions`, `self_test`
- `temp_dir` fixture — provided externally (conftest.py), yields a `pathlib.Path` to a temporary directory
