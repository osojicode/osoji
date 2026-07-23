# packages\adapter-javascript\scripts\build-js-debug.js
@source-hash: 07305e786f1edb07
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:29Z

## Purpose

Build script that vendors Microsoft's `js-debug` (`vscode-js-debug`) DAP server (`vsDebugServer.js`) into `vendor/js-debug/`. Supports three acquisition modes: prebuilt GitHub release download (default), local path override, and build-from-source fallback. Produces deterministic output: `vsDebugServer.js`, `vsDebugServer.cjs`, `vsDebugServer.js.sha256`, `manifest.json`, and runtime sidecars.

## Key Constants (L37–51)

| Constant | Value |
|---|---|
| `VERSION` | `process.env.JS_DEBUG_VERSION \|\| 'latest'` |
| `FORCE` | `process.env.JS_DEBUG_FORCE_REBUILD === 'true'` |
| `GH_TOKEN` | `process.env.GH_TOKEN \|\| process.env.GITHUB_TOKEN \|\| ''` |
| `VENDOR_DIR` | `<pkg-root>/vendor/js-debug` |
| `VENDOR_FILE` | `<vendor-dir>/vsDebugServer.js` |
| `VENDOR_FILE_CJS` | `<vendor-dir>/vsDebugServer.cjs` |
| `CHECKSUM_FILE` | `<vendor-dir>/vsDebugServer.js.sha256` |
| `MANIFEST_FILE` | `<vendor-dir>/manifest.json` |
| `REPO_OWNER` | `'microsoft'` |
| `REPO_NAME` | `'vscode-js-debug'` |
| `API_BASE` | `'https://api.github.com'` |

## Core Functions

### `main()` (L482–793)
Top-level orchestrator. Flow:
1. **Skip check**: `SKIP_ADAPTER_VENDOR=true` → exit 0 immediately (L484–488).
2. **Cache check**: If artifact + sidecars (`bootloader.js`, `hash.js`) exist and `FORCE` is false → exit 0 (L493–497). Warns if artifact present but sidecars missing (L498–503).
3. **Dispatch on vendoring plan** (from `determineVendoringPlan`):
   - `plan.mode === 'local'`: Copy local file → write checksum + manifest → exit (L509–548).
   - `plan.mode === 'prebuilt'` or `'prebuilt-then-source'`: Full GitHub download flow (L550–793).
4. **Prebuilt flow** (L550–722): fetch release JSON → select best asset → download archive → extract → find server entry → copy main file + `.cjs` copy → copy sidecars → copy `vendor/` subdirectory → write `package.json` forcing CJS → write checksum + manifest.
5. **Hard sidecar check** (L618–631): Throws if `bootloader.js` or `hash.js` missing after extraction.
6. **Source override** (L679–720): If `plan.mode === 'prebuilt-then-source'`, additionally builds from source and overwrites prebuilt artifact.
7. **Prebuilt failure → source fallback** (L724–774): If prebuilt throws and `plan.mode === 'prebuilt-then-source'`, invokes `buildFromSource`.
8. **Final error messages** (L776–789): Actionable tips for 403/404/missing asset errors.

### `getRelease(version)` (L108–167)
Fetches GitHub release JSON with 3-attempt retry + exponential backoff (500ms base). Handles 404 (no retry), 403 with rate limit details, 5xx (retry), other errors (throw). `version === 'latest'` uses `/releases/latest`; otherwise `/releases/tags/:tag`.

### `downloadWithRetries(url, destFile)` (L169–217)
Downloads binary asset with 3-attempt retry + exponential backoff. Validates `content-length` header. Saves to `destFile`. Throws with actionable GH_TOKEN tip on 403.

### `extractArchive(archiveFile, type, outDir)` (L219–233)
Extracts `.tgz` (via `tar.extract`) or `.zip` (via `extract-zip`) to `outDir`. Throws on unsupported type.

### `findServerEntry(rootDir)` (L269–320)
BFS search for DAP server entry. Priority order:
1. `dist/vsDebugServer.js`
2. `dist/src/dapDebugServer.js`
3. `extension/src/dapDebugServer.js`
4. `js-debug/src/dapDebugServer.js`
5. BFS for any `dapDebugServer.js` or `vsDebugServer.js`
Returns `{ abs, rel }`. Throws with sampled file listing if not found.

### `buildFromSource(version)` (L417–457)
Clones the vscode-js-debug repo to a temp dir, installs dependencies using auto-detected package manager (yarn/pnpm/npm), runs `gulp vsDebugServerBundle`, copies built artifact to a permanent temp location, and returns the path. Cleans up source clone.

### `detectRepoPackageManager(repoDir)` (L398–411)
Detects whether to use yarn (yarn.lock + yarn available), pnpm (pnpm-lock.yaml + pnpm available), or npm fallback. Uses platform-specific command names on Windows.

### `fetchJsonWithTimeout(url, opts)` (L67–86)
Single GitHub API fetch with AbortController signal, injects GH_TOKEN authorization and standard headers. Returns `{ resp, data, text }`.

### `execCmd(cmd, args, opts)` (L356–387)
Wraps `spawn` as a Promise. On Windows, auto-retries with `shell: true` on spawn error. Returns `{ stdout, stderr }` on exit code 0.

### `sha256File(filePath)` (L322–331)
Streams a file and returns its SHA-256 hex digest.

### `writeChecksum(filePath, checksumPath)` (L333–337)
Writes SHA-256 hex + newline to checksumPath, returns the hash.

### `writeManifest({ source, repo, version, asset, sha256, original })` (L339–350)
Writes JSON manifest to `MANIFEST_FILE` with `fetchedAt` timestamp.

### `findAllByBasename(rootDir, targetNames)` (L459–480)
Full BFS search returning all files whose basename is in `targetNames` Set.

### `sampleFiles(rootDir, limit)` (L236–258)
BFS-samples up to `limit` files for error reporting.

### `safeRmRf(p)` (L96–102), `makeTmpDir(prefix)` (L92–94), `delay(ms)` (L88–90)
Utility helpers for temp dir management and timing.

## Manifest `source` Values (produced strings)
- `'local'` — copied from `JS_DEBUG_LOCAL_PATH`
- `'prebuilt'` — downloaded from GitHub releases
- `'source-override'` — prebuilt downloaded then overridden by source build
- `'source'` — only source build succeeded

## Vendoring Plan Modes (from `determineVendoringPlan`)
- `'local'` — use `JS_DEBUG_LOCAL_PATH`
- `'prebuilt'` — default GitHub release download
- `'prebuilt-then-source'` — download first, source build as fallback/override

## Architectural Decisions
- **CJS enforcement**: Always copies `vsDebugServer.js` → `vsDebugServer.cjs` and writes a `package.json` with `"type": "commonjs"` in `vendor/js-debug/` to prevent ESM resolution issues.
- **Sidecar copying**: Two passes — first from adjacent files in server directory, then BFS for `bootloader.js`/`watchdog.js`/`hash.js` anywhere in extract tree. Hard failure if `bootloader.js` or `hash.js` missing.
- **Idempotency**: Skips if artifact and required sidecars present (unless `FORCE=true`).
- **Retry**: All network operations use 3-attempt exponential backoff (500ms, 1000ms base).
- **Cross-platform**: Platform-specific command names on Windows (`.cmd` suffix), shell fallback for spawn errors.

## Dependencies
- `tar` (npm: `tar`) — tgz extraction
- `extract-zip` — zip extraction
- `fs-extra` (`ensureDir`, `copy`) — directory creation and recursive copy
- `./lib/js-debug-helpers.js` — `selectBestAsset`, `normalizePath`
- `./lib/vendor-strategy.js` — `determineVendoringPlan`
