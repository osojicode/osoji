# tests\test-utils\helpers\show-failures.js
@source-hash: 82fa542f2679d47c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:49Z

## Purpose
A standalone CLI script that runs the Vitest test suite with JSON output and displays only test failures in a human-readable, filtered format. Intended as a developer utility to quickly surface actionable failure information without noise from `node_modules` stack frames.

## Key Function

### `showFailures` (L8–84)
Async function that orchestrates the full test-run-and-report workflow:

1. **Spawns Vitest** (L15–18): Runs `npx vitest run --reporter=json --outputFile <cwd>/test-results.json` via `child_process.spawn` with `shell: true` and `stdio: 'inherit'` (live output to terminal during run).
2. **Awaits process exit** (L20–22): Resolves when the spawned process closes, regardless of exit code.
3. **Reads JSON results** (L25–31): Checks for existence of `test-results.json` at CWD; exits with code 1 if missing.
4. **Parses `testResults` array** (L33–37): Skips analysis if no results present; deletes the JSON file and returns.
5. **Iterates test files** (L42–67): For each `testFile`, filters `assertionResults` by `status === 'failed'`. Prints relative path (L47), separator, and numbered list of failures with cleaned `failureMessages` (strips `node_modules` lines, `at async` lines, and blank lines).
6. **Summary output** (L69–74): Prints `✅ All tests passed!` or total failure count from `results.numFailedTests`.
7. **Cleanup** (L77): Deletes `test-results.json` after processing.
8. **Error handling** (L79–83): Catches JSON parse errors; exits with code 1.

## Entry Point (L87–90)
Immediately invokes `showFailures()` at module level. Any unhandled rejection logs the error and calls `process.exit(1)`.

## JSON Result Schema Expected
- `results.testResults[]` — array of test file result objects
  - `.name` — absolute file path
  - `.assertionResults[]` — per-test results
    - `.status` — `'failed'` | `'passed'` | etc.
    - `.fullName` / `.title` — test display name
    - `.failureMessages[]` — raw error strings
- `results.numFailedTests` — total failure count

## Dependencies
- Node.js `child_process.spawn` for subprocess execution
- Node.js `fs` for file existence check, read, and delete
- Node.js `path` for CWD-relative path construction

## Output File
`test-results.json` written to `process.cwd()` (L9), always deleted after processing (L35, L77).

## Architectural Notes
- No exported symbols; this is a self-executing entry script.
- `stdio: 'inherit'` (L16) means Vitest's own stdout/stderr is streamed live to the terminal during the run, before the JSON summary phase begins.
- Error message filtering (L57–61) removes `node_modules` and `at async` trace lines to show only relevant assertion output.
- The `shell: true` flag (L17) is required for `npx` resolution on Windows.