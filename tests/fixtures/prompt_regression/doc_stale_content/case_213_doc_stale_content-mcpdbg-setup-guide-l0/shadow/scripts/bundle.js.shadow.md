# scripts\bundle.js
@source-hash: e446cc34cebb3883
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:18Z

## Purpose
Build script that bundles the MCP debugger server into self-contained CJS files using esbuild. Produces two artifacts: the main server bundle (`dist/bundle.cjs`) and a DAP proxy bundle (`dist/proxy/proxy-bundle.cjs`).

## Entry Point
Module-level call `bundle()` at L175 — script runs immediately when executed.

## Key Function: `bundle()` (L10–173)
Async function performing the full build pipeline:

### Phase 1: Main Bundle (L15–34)
Runs `esbuild.build()` with:
- Entry: `dist/index.js` → Output: `dist/bundle.cjs`
- Platform: `node`, target: `node18`, format: `cjs`
- `fsevents` kept external (native module)
- `minify: true`, `sourcemap: false`
- `import.meta.url` hardcoded to `file:///app/dist/bundle.cjs`
- `__dirname` hardcoded to `/app/dist`

### Phase 2: Bundle Post-Processing (L36–102)
1. Writes metafile to `dist/bundle-meta.json` (L37)
2. Reads generated bundle (L40)
3. Strips shebang lines from bundled content via regex replace (L43)
4. Prepends `consoleSilencer` IIFE (L45–99) that:
   - Detects `stdio` or `sse` transport via `process.argv` matching (`matchesKeyword` helper checks `=keyword`, `:keyword`, `--transport=keyword` patterns)
   - Also triggers on `CONSOLE_OUTPUT_SILENCED=1` env var
   - Replaces all console methods with `noop` (L74–86)
   - Removes process warning listeners (L89–90)
   - Strips surrounding quotes from all `process.argv` entries (L95–97) — argv cleanup happens unconditionally regardless of transport mode
5. Writes modified bundle back to `dist/bundle.cjs` (L102)

### Phase 3: Proxy Bootstrap Copy (L104–115)
Copies `src/proxy/proxy-bootstrap.js` → `dist/proxy/proxy-bootstrap.js` if the source exists. Creates `dist/proxy/` directory if needed.

### Phase 4: Analysis & Size Reporting (L117–127)
Reports bundle size in MB, runs `esbuild.analyzeMetafile()`.

### Phase 5: Proxy Bundle (L129–167)
Runs second `esbuild.build()`:
- Entry: `dist/proxy/dap-proxy-entry.js` → Output: `dist/proxy/proxy-bundle.cjs`
- Platform: `node`, target: `node20`, format: `cjs`
- `external: []` — bundles ALL dependencies
- `minify: false`, `sourcemap: 'inline'`, `keepNames: true`
- `import.meta.url` hardcoded to `file:///app/dist/proxy/proxy-bundle.cjs`
- `__dirname` hardcoded to `/app/dist/proxy`
- Exits with code 1 if output file not found (L165–167)

## Error Handling
Top-level `try/catch` (L13/L169–172) logs error and calls `process.exit(1)` on any failure.

## Critical Design Decisions
- **Console silencing prepended to bundle**: The MCP stdio/SSE transport protocols are broken by any stdout/stderr output. The IIFE must run before any module-level code in the bundle.
- **Hardcoded paths for `import.meta.url`/`__dirname`**: Assumes deployment at `/app/dist/` — production Docker container path convention.
- **Argv quote stripping is unconditional**: Runs for all transport modes, not just stdio/SSE (L95–97). This may be intentional to normalize shell-quoted arguments.
- **Proxy target is `node20` vs main target `node18`**: Proxy uses a newer Node target.
