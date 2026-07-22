# tests\test-utils\helpers\test-coverage-summary.js
@source-hash: 9f3c0a3356b42ad9
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:10Z

## Purpose
CLI entry-point script that spawns a Vitest run with coverage, suppresses verbose output, then reads the generated JSON artifacts to print a compact summary table and exits with the appropriate code.

## Key Function

### `testCoverageSummary` (L8–135)
Async orchestrator. No parameters. Steps:
1. **Paths** (L9–10): Resolves `test-results.json` (process.cwd()) and `coverage/coverage-summary.json` relative to CWD.
2. **Spawn** (L16–21): Calls `npx vitest run --coverage --reporter=json --outputFile <jsonFile>` via `spawn` with `shell:true`, stdout/stderr piped.
3. **Progress filtering** (L24–31): Listens on `stdout`; extracts only `[·.xX!*]+` characters (dot-style progress) and writes them to `process.stdout`. stderr is silently swallowed (L33).
4. **Await exit** (L37–39): Resolves child process `close` event; propagates non-zero exit code to `process.exitCode` (L40–42).
5. **Parse test results** (L62–76): Reads Vitest JSON reporter output (`numTotalTestSuites`, `numPassedTestSuites`, `numFailedTestSuites`, `numPendingTestSuites`, `numTotalTests`, `numPassedTests`, `numFailedTests`, `numPendingTests`). Guards with `existsSync`.
6. **Parse coverage** (L87–97): Reads Istanbul `coverage-summary.json`; extracts `total.{statements,branches,functions,lines}.pct`.
7. **Print summary** (L100–106): 70-char divider lines with test file counts, test counts, duration, and coverage percentages.
8. **Exit code logic** (L109): Exits 1 if any suite or test failed, else 0. Note: overrides `process.exitCode` set in step 4 — the child's exit code is NOT used directly for the final `process.exit()` call; only the parsed failure counts matter.
9. **Cleanup** (L112–114): Deletes `test-results.json` after reading.
10. **Error path** (L118–134): On JSON parse or other error, prints a fallback message and exits 1; also cleans up the JSON file.

## Module-level execution
L138–141: Immediately calls `testCoverageSummary()` and attaches a top-level `.catch` that exits 1 on unexpected errors.

## Dependencies
- `child_process.spawn` — runs `npx vitest`
- `fs` — `existsSync`, `readFileSync`, `unlinkSync`
- `path.join` — path construction
- External artifacts: Vitest JSON output (`test-results.json`) and Istanbul/v8 coverage summary (`coverage/coverage-summary.json`)

## Architectural Notes
- `shell: true` is required to resolve `npx` on Windows.
- The final exit code (L109/116) is driven by **parsed failure counts**, not the child process exit code. The child exit code only sets `process.exitCode` (L41) as a side-effect but `process.exit(exitCode)` at L116 supersedes it.
- Coverage percentages use mixed precision: `toFixed(2)` for statements/functions, `toFixed(1)` for branches/lines (L105) — likely unintentional inconsistency.
- No cleanup on unhandled promise rejection path (L138–141); the temp JSON file may persist if `testCoverageSummary` itself rejects before the catch block at L118.
