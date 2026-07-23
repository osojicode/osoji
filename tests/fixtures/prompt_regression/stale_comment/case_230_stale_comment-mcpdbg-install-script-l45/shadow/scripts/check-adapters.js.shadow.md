# scripts\check-adapters.js
@source-hash: 1c299f30347c5903
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:51Z

## Purpose
CLI script that checks the vendoring status of all debug adapters in the project, producing a formatted status report and exiting with code 1 if any adapter is missing (except in CI environments).

## Architecture
- ESM module with `import.meta.url`-based `__dirname` shim (L12–14)
- Adapter dispatch in `main()` (L235–242) is string-based: routes to `checkJavaScriptAdapter` or `checkRustAdapter` by checking if `adapter.name` includes `"JavaScript"` or `"Rust"`
- `rootDir` is resolved as one level up from `scripts/` (L14)

## Key Symbols

### Module-level constants
- `adapters` (L17–32): Static array of adapter config objects. Two entries:
  1. JavaScript (js-debug): checks `packages/adapter-javascript/vendor/js-debug/vsDebugServer.js`, reads version from `manifest.json`, validates sidecars `bootloader.js` and `hash.js`
  2. Rust (CodeLLDB): checks `packages/adapter-rust/vendor/codelldb/{platform}/adapter/codelldb[.exe]` across 5 platforms

### Functions

- `getCurrentPlatform()` (L37–48): Maps `process.platform` + `process.arch` to one of 5 known platform strings (`win32-x64`, `darwin-x64`, `darwin-arm64`, `linux-x64`, `linux-arm64`); falls back to `${platform}-${arch}`

- `exists(filePath)` (L53–60): Uses `fs.accessSync` for path existence; returns boolean, swallows all errors

- `readJsonSafe(filePath)` (L65–71): Reads and parses JSON file; returns `null` on any error

- `checkJavaScriptAdapter(adapter)` (L76–116): Returns status object `{ name, vendored, version, source, sidecars, issues }`. Checks main vendor file, reads manifest for version/source, validates each required sidecar file.

- `checkRustAdapter(adapter)` (L121–166): Returns status object `{ name, vendored, currentPlatform, platforms, issues }`. Iterates all 5 platforms; marks `status.vendored = true` only when the *current* platform's binary is present. Each platform entry: `{ vendored, version?, current }`.

- `formatStatus(status)` (L171–218): Prints color-coded (ANSI) adapter status to stdout. Handles both JS (sidecars display) and Rust (platforms display) via duck-typing on status fields.

- `main()` (L223–272): Entry point. Iterates `adapters`, dispatches by name, collects statuses, prints summary. Exits with code 1 if `!allVendored && process.env.CI !== 'true'`.

### Direct invocation guard
- `invokedDirectly` (L274): Resolves `process.argv[1]` against `__filename` to safely support both direct execution and import-as-module.

## Key Behaviors
- Adapter type dispatch (L235–242) relies on `adapter.name` string containing `"JavaScript"` or `"Rust"` — coupling between config and dispatch
- Rust adapter considers itself "vendored" only if the **current platform** binary exists (L149–152); all other platform statuses are informational
- Windows detection for binary name: `platform.startsWith('win')` → `codelldb.exe`, else `codelldb` (L138–139)
- CI bypass: non-zero exit is suppressed when `process.env.CI === 'true'` (L269)
- `status.source` field is written in `checkJavaScriptAdapter` (L97) but read in `formatStatus` (L182–184) — no equivalent in Rust adapter

## Dependencies
- Node.js built-ins only: `fs`, `path`, `url`
- No external npm packages