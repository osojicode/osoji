# analyze-coverage.js
@source-hash: 31352ccb68ee169c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:55Z

## Coverage Attribution Analysis Script

Post-test script that reads `coverage/coverage-summary.json` and prints a compact, sorted table of the top 10 files with the most uncovered lines to stdout. Designed to run automatically after `npm run test:coverage`.

### Execution Flow (module-level, no exports)

1. **Path resolution (L10-11):** Uses `fileURLToPath` + `path.dirname` to compute `__dirname` for ESM compatibility.
2. **Guard (L16-19):** Silently exits (`process.exit(0)`) if `coverage/coverage-summary.json` does not exist — tolerates environments without coverage output.
3. **Data loading (L21-22):** Parses the JSON summary; extracts `coverage.total.lines.pct` as `overall`, defaulting to `0` if missing.
4. **File aggregation (L24-43):** Iterates all keys except `"total"`, computes `uncovered = data.lines.total - data.lines.covered`, strips `process.cwd()` prefix from absolute paths, normalises separators to `/`.
5. **Impact calculation (L46-48):** Appends `impact` field to each file entry: `(uncovered / totalLines) * 100`, representing each file's drag on overall coverage.
6. **Sorting (L51):** Sorts files descending by `uncovered` line count.
7. **Output (L54-87):** Prints a 70-char wide box with overall %, a table of up to 10 files (columns: uncovered lines, coverage %, impact %, truncated path), and a trailing hint to run detailed analysis.
8. **Error handling (L89-92):** Any thrown error is silently swallowed; prints `[Coverage analysis unavailable]` to avoid disrupting test pipelines.

### Key Details
- **No exports** — pure side-effect script, runs as ESM entry point.
- Path truncation (L68-70): paths longer than 45 chars are shortened to `'...' + last 42 chars`.
- Column format (L72-77): right-padded numbers, fixed-decimal percentages, `+X.X%` impact prefix.
- Top-N cap (L61, L80-82): displays first 10, shows `... +N more files` if there are additional entries.