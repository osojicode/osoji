# tests\test-utils\helpers\test-coverage-summary.js
@source-hash: 7a9bfee219ed7412
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:43Z

## Purpose
CLI script that spawns a Vitest test run with coverage, suppresses verbose output, then reads the generated JSON result files and prints a compact summary table before exiting with an appropriate exit code.

## Key Function

### `testCoverageSummary` (L8–135)
Async, self-invoked entry point. Execution flow:
1. **Resolve output paths** (L9–10): `test-results.json` (cwd) and `coverage/coverage-summary.json` (cwd).
2. **Spawn Vitest** (L16–21): `npx vitest run --coverage --reporter=json --outputFile <jsonFile>` via `child_process.spawn` with `shell: true`, piped stdout/stderr.
3. **Filter stdout** (L24–31): Regex `/[·.xX!*]+/g` extracts only progress dot characters; all other output is dropped.
4. **Suppress stderr** (L33)**: No-op handler — stderr is completely silenced.
5. **Await exit code** (L37–42): Resolves child process close event; propagates non-zero exit via `process.exitCode`.
6. **Parse test results** (L62–77): Reads `test-results.json` if present; maps Vitest JSON fields (`numTotalTestSuites`, `numPassedTestSuites`, `numFailedTestSuites`, `numPendingTestSuites`, `numTotalTests`, `numPassedTests`, `numFailedTests`, `numPendingTests`).
7. **Parse coverage** (L87–97): Reads `coverage/coverage-summary.json` if present; extracts `total.statements.pct`, `total.branches.pct`, `total.functions.pct`, `total.lines.pct`.
8. **Print summary** (L100–106): Fixed 70-char separator lines with test file counts, test counts, duration, and coverage percentages.
9. **Cleanup** (L112–113): Deletes `test-results.json`.
10. **Exit** (L116): `process.exit(Math.max(childExitCode ?? 0, exitCode))` — takes the worse of the two codes.
11. **Error path** (L118–134): Logs error message and a minimal fallback summary, cleans up, exits with code 1.

## Module-level invocation (L138–141)
`testCoverageSummary()` is called immediately; unhandled rejections exit with code 1.

## Key Design Decisions
- `shell: true` on spawn required for `npx` cross-platform compatibility.
- `coverage.statements.pct` formatted with `.toFixed(2)`, branches/lines with `.toFixed(1)` — inconsistent precision (intentional or oversight).
- Exit code is `Math.max(childExitCode ?? 0, exitCode)` where `exitCode` is re-derived from parsed JSON (L109), so a Vitest failure reported in JSON but child exit 0 still exits non-zero.
- Temporary `test-results.json` is always cleaned up; `coverage-summary.json` is left in place.
- stderr of child process is completely swallowed with an empty handler (L33).
