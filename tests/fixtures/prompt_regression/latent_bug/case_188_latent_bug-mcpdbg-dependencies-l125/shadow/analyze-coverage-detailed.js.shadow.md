# analyze-coverage-detailed.js
@source-hash: 9f892e7d5abdec98
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:30Z

## Overview
A standalone CLI analysis script that reads a Jest/Istanbul `coverage-summary.json` file and prints a formatted, prioritized report of uncovered lines per file. Intended to be run manually via `npm run test:coverage:analyze` after generating coverage data.

## Execution Model
- ES module script using `import.meta.url` for `__dirname` emulation (L10–11)
- Entire logic wrapped in a single top-level `try/catch` (L13–101); exits with code 1 on error or missing coverage file
- No exported symbols — purely a script entry point

## Key Logic Flow

### 1. Coverage File Resolution & Parsing (L14–22)
- Resolves `coverage/coverage-summary.json` relative to the script's own directory
- Exits with code 1 if file is absent (L16–19)
- Parses JSON; reads `coverage.total.lines.pct` as the overall percentage (L22)

### 2. Per-File Aggregation (L28–45)
- Iterates all entries in the coverage JSON, skipping the `"total"` key (L29)
- For each file: computes `uncovered = data.lines.total - data.lines.covered` (L31)
- Strips CWD prefix and normalises path separators to `/` (L36–37)
- Builds a `files` array of `{ path, coverage, uncovered, total }` objects (L39–44)

### 3. Impact Calculation (L48–50)
- Adds `impact` field to each file: `(file.uncovered / totalLines) * 100`
- Represents how many overall percentage points would be gained if that file reached 100%

### 4. Sorted Output (L53–75)
- Sorts files descending by `uncovered` line count (L53)
- Prints a table header then each file with `uncovered > 0` (L66–75)
- Columns: uncovered count, line coverage %, impact %, file path

### 5. Insights Section (L85–94)
- Takes top-5 files (L85)
- Reports sum of their uncovered lines and projected coverage gain (L87–89)
- If the top file has >50 uncovered lines, prints a priority callout (L91–94)

## Dependencies
- `fs` (Node stdlib): file existence check and synchronous read
- `path` (Node stdlib): path joining and directory resolution
- `url` (Node stdlib): `fileURLToPath` for ESM `__dirname` pattern

## Expected Input Shape (`coverage-summary.json`)
```json
{
  "total": { "lines": { "pct": 82.5, "total": 1000, "covered": 825 } },
  "/abs/path/to/file.ts": { "lines": { "pct": 60.0, "total": 100, "covered": 60 } }
}
```

## Notable Constraints
- Reads only `lines` metrics; `statements`, `functions`, `branches` are ignored
- Path normalisation uses `process.cwd()` to strip the project root prefix (L36); if the script is run from a different working directory than the project root, paths may not be cleaned correctly
- `overall` falls back to `0` if `coverage.total` is absent (L22), but the script does not warn about this case