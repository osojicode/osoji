# tests\test-utils\helpers\test-results-analyzer.js
@source-hash: d23d28abfacee37b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:40Z

## TestResultsAnalyzer (L7-230)

CLI utility that reads a Jest JSON test results file and displays analysis at three verbosity levels: `summary`, `failures`, or `detailed`. Intended to be run directly via Node.js (`node test-results-analyzer.js`), not imported as a module.

### Class: `TestResultsAnalyzer` (L7-230)

#### Constructor (L8-10)
- `jsonFile` defaults to `'test-results.json'`
- Resolves path relative to `process.cwd()` via `path.join`

#### `analyze(level)` (L12-44)
- Entry point — reads and parses the JSON file, dispatches to one of three display methods
- Valid `level` values: `'summary'`, `'failures'`, `'detailed'`
- Hard exits (`process.exit(1)`) on missing file, unknown level, or parse errors
- Detects `SyntaxError` specifically for malformed JSON

#### `showSummary(results)` (L46-78)
- Reads top-level Jest JSON fields: `numTotalTests`, `numPassedTests`, `numFailedTests`, `numPendingTests`, `numTotalTestSuites`, `numPassedTestSuites`, `numFailedTestSuites`, `startTime`, `success`, `coverageMap`
- Prints suite-level and test-level counts with Unicode status symbols
- Mentions coverage map presence but does NOT display it; refers user to `--level=detailed` (note: `showDetailed` also does not break down coverage — this hint is misleading)

#### `showFailures(results)` (L80-141)
- Iterates `results.testResults[]`, filters `assertionResults` with `status === 'failed'`
- For each failure: prints relative file path, test title/fullName, status, duration, and filtered error messages
- Stack trace filtering logic (L121-133): sets `inStackTrace = true` when a line contains `'at '` or `'node_modules'`, then resets to `false` on the very next line — this does NOT reliably suppress multi-line stack traces (the flag is reset each iteration rather than being sticky)

#### `showDetailed(results)` (L143-229)
- Calls `showSummary` first (L148), then groups test files by directory using `path.dirname`
- Displays hierarchical directory/file breakdown with pass/fail/skipped counts and duration
- Appends a performance section listing the top 10 slowest tests (threshold: >1000ms, L210)
- Duration per file computed as `testFile.endTime - testFile.startTime` (L174); if either is missing/undefined this produces `NaN`, falling back to `|| 0`

### Module-level CLI bootstrap (L232-264)
- Parses `process.argv` for `--level=`, `--file=`, `--help`/`-h`
- Instantiates `TestResultsAnalyzer` and calls `.analyze()` immediately on load (L260-263)
- This means **importing this file as a module will trigger CLI execution** — there is no guard

### Key architectural notes
- No exports; this is a pure CLI script
- All output goes to `console.log`/`console.error`; no structured return values
- Relies on Jest's JSON reporter format (`--json` / `jest --outputFile`)