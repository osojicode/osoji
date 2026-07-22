# scripts\check-bundle-size.js
@source-hash: 235d3ba0b8152e38
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:35Z

## Bundle Size Checker Script

CLI script that validates the `mcp-debugger` package bundle size against defined thresholds and reports adapter presence.

### Constants (L16-17)
- `WARN_SIZE_MB = 8` — soft threshold; prints a warning but exits 0
- `ERROR_SIZE_MB = 15` — hard threshold; exits with code 1

### Core Function: `checkBundleSize` (L19-94)
Async function (immediately invoked at L96) that:
1. Resolves `packages/mcp-debugger/dist/` relative to the script's parent directory (L20-21)
2. Exits 0 with a message if `dist/` or `dist/cli.mjs` do not exist (L24-34)
3. Uses `fs.statSync` to read `cli.mjs` file size (L36-38)
4. Prints size in both MB and KB (L43)
5. Applies threshold logic:
   - `> 15 MB` → prints error suggestions, exits 1 (L46-53)
   - `> 8 MB` → prints warning, continues (L54-58)
   - `≤ 8 MB` → prints success (L59-62)
6. Optionally reads `dist/bundle-meta.json` (esbuild metafile format) and checks for three adapter path substrings: `adapter-javascript`, `adapter-python`, `adapter-mock` (L65-88)
   - Warns to stdout if `adapter-javascript` is absent (critical for npx distribution)

### Entry Point (L96-99)
Top-level `checkBundleSize().catch(...)` — unhandled errors print to stderr and exit 1.

### ESM Module Setup (L11-13)
Uses `fileURLToPath(import.meta.url)` pattern to reconstruct `__dirname` in an ES module context, then resolves the monorepo root as one level up (`..`).

### Exit Codes
| Code | Condition |
|------|-----------|
| 0    | dist missing, cli.mjs missing, or size ≤ error threshold |
| 1    | size > 15 MB, or unexpected thrown error |

### Bundle Meta Format Assumption
Expects `bundle-meta.json` to be a JSON object with an `inputs` key whose value is a map of file paths (esbuild metafile schema). If the file is absent the meta section is silently skipped.