# mcp_debugger_launcher\tests\test_launcher.py
@source-hash: 1b81f3b89c6d6785
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:10Z

## Overview
Manual integration/smoke test script for the `mcp_debugger_launcher` package. Exercises runtime detection, command construction (dry run), and CLI module importability. Not a pytest/unittest suite — runs as a standalone script via `__main__` and prints human-readable results.

## Key Functions

### `test_runtime_detection()` (L11–43)
Exercises `RuntimeDetector` through its full public API:
- `RuntimeDetector.check_nodejs()` → `(bool, str|None)` (L18)
- `RuntimeDetector.check_npx()` → `bool` (L24)
- `RuntimeDetector.check_docker()` → `(bool, str|None)` (L28)
- `RuntimeDetector.detect_available_runtimes()` → `dict` with `"nodejs"` and `"docker"` keys (L35)
- `RuntimeDetector.get_recommended_runtime(runtimes)` → runtime name string (L40)
Returns the `runtimes` dict (used in `main()` summary check at L97).

### `test_dry_run()` (L45–66)
Constructs and prints expected CLI commands using `DebugMCPLauncher` class constants:
- `launcher.NPM_PACKAGE` (L53, L57)
- `launcher.DOCKER_IMAGE` (L61, L65)
No subprocess calls are made; purely verifies constant access and visual output.

### `test_cli_import()` (L68–81)
Dynamically imports the `cli` module (resolved via the `sys.path` insertion at L6) and checks:
- `cli.__version__` attribute (L76)
- `cli.main` function reference (L77)
Returns `True` on success, `False` on any exception.

### `main()` (L83–109)
Orchestrates all three tests, collects results, prints a summary. Final summary logic (L97) accesses `runtimes["nodejs"]["available"]` and `runtimes["docker"]["available"]` — nested dict access assuming the structure returned by `detect_available_runtimes()`.

## Architectural Notes
- `sys.path.insert(0, os.path.dirname(__file__))` (L6) makes sibling modules (`detectors`, `launcher`, `cli`) importable without package installation.
- No assertions or test framework — failures are caught/printed, not raised. The script always exits 0.
- Entry point is `if __name__ == "__main__": main()` (L111–112).
