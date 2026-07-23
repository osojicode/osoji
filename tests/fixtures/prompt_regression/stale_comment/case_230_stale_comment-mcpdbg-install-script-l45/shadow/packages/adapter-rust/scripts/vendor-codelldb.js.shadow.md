# packages\adapter-rust\scripts\vendor-codelldb.js
@source-hash: acd31303883b83df
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:16Z

## Purpose
Node.js ESM script that downloads, caches, and extracts CodeLLDB VSIX packages from GitHub releases into a `vendor/codelldb/` directory for use by the Rust debug adapter. Supports multi-platform vendoring, disk-based artifact caching with SHA256 validation, retry logic, and CI/local dev differentiation.

## Key Constants (L31–42)
- `CODELLDB_VERSION` (L31): Version string, default `'1.11.8'`, overridden by env var.
- `VENDOR_DIR` (L32): `<package-root>/vendor/codelldb` — extraction destination.
- `FORCE_REBUILD`, `IS_CI`, `SKIP_VENDOR`, `KEEP_TEMP`, `LOCAL_ONLY` (L33–37): Boolean flags driven by environment variables.
- `RELEASE_BASE_URLS` (L38–42): Array of two GitHub release base URLs tried in order; first is configurable via `CODELLDB_RELEASE_BASE`.
- `cacheWritable` (L44): Mutable boolean; set to `false` in `main()` (L690) if the cache directory cannot be created.
- `CACHE_DIR` (L45): Resolved at module load by `determineCacheDir()`.

## Platform Map — `PLATFORMS` (L47–78)
Supports 5 targets: `win32-x64`, `darwin-x64`, `darwin-arm64`, `linux-x64`, `linux-arm64`. Each entry has:
- `vsixNames`: Ordered list of VSIX filename candidates to try (new naming convention first).
- `binaryPath`: Relative path to main executable inside the VSIX.
- `libPath`: Relative path to liblldb inside the VSIX.
- `targetDir`: Subdirectory name under `VENDOR_DIR`.

## Key Functions

### `getCurrentPlatform()` (L83–94)
Maps `process.platform`/`process.arch` to a PLATFORMS key. Returns `null` for unsupported combos.

### `determineCacheDir()` (L119–148)
Resolves platform-appropriate cache directory (`LOCALAPPDATA`, `XDG_CACHE_HOME`, macOS Library/Caches, `~/.cache`, or `os.tmpdir()`). Subdirectory: `debug-mcp/codelldb/<version>`.

### Cache Management (L150–265)
- `sanitizeCacheFileName(name)` (L150–152): Replaces non-alphanumeric chars with `_`.
- `getCacheEntryPaths(vsixName)` (L154–162): Returns `{filePath, metaPath}` or `null` if cache is disabled.
- `loadCacheEntry(vsixName)` (L164–205): Validates version + SHA256 hash before returning cached artifact. Invalidates on mismatch.
- `invalidateCacheEntry(vsixName)` (L207–214): Removes cached file and `.json` metadata.
- `saveArtifactToCache(vsixName, sourcePath)` (L232–265): Atomic copy (rename with EXDEV cross-device fallback) + SHA256 metadata write.
- `tryUseCachedArtifact(platform, platformInfo, vsixName)` (L216–230): Tries cache first; on success calls `extractAndCopyFiles`.

### `computeSha256(filePath)` (L281–296)
Promise-based SHA256 hash of a file via streaming `createReadStream` → `createHash`.

### `downloadFile(url, destPath, maxRetries=3)` (L301–370)
- Fetches with 30s `AbortController` timeout.
- Shows `ProgressBar` in non-CI; logs MB size in CI.
- Uses `Readable.fromWeb` + `pipeline` for streaming write.
- Validates downloaded size against `Content-Length`.
- Exponential backoff: `500 * 2^(attempt-1)` ms.

### `extractAndCopyFiles(vsixPath, platform, platformInfo, vsixName)` (L375–460)
- Validates ZIP magic bytes (`504b0304`).
- Extracts to `temp-<platform>` subdir via `extractZip`.
- Copies full `extension/adapter/` and `extension/lldb/` directory trees.
- Sets `0o755` on the main binary for non-Windows platforms.
- Optionally copies `extension/lang_support/` if present.
- Writes `version.json` manifest with version, platform, timestamp.
- Cleans up temp dir unless `KEEP_TEMP`.

### `copyDirectory(src, dest)` (L465–482)
Recursive directory copy preserving file mode bits.

### `isAlreadyVendored(platform, platformInfo)` (L496–509)
Reads `version.json`; returns `true` if version matches `CODELLDB_VERSION` and `FORCE_REBUILD` is false.

### `downloadAndExtract(platform)` (L514–604)
Orchestrates for a single platform:
1. Checks `isAlreadyVendored`.
2. Enforces `LOCAL_ONLY` guard.
3. Iterates `vsixCandidates × baseUrls × attempts`.
4. Cache → download → extract → cache save flow.

### `determinePlatforms()` (L609–658)
Priority order: `CODELLDB_PLATFORMS` env → CLI args → CI logic → local dev logic.
- CI default: current platform only (override with `CODELLDB_VENDOR_ALL=true`).
- Local default: all platforms (override with `CODELLDB_VENDOR_ALL=false`).

### `main()` (L663–757)
Entry point: logs environment state, initializes cache dir, creates `.gitkeep` files, runs `downloadAndExtract` for each selected platform sequentially, prints summary. In CI, exits with code 1 on any failure; locally sets `process.exitCode`.

## Invocation (L759–771)
Script is self-invoking when run directly (detected via `process.argv[1]` comparison). Also exports `downloadAndExtract`, `PLATFORMS`, `CODELLDB_VERSION` for programmatic use.

## Architecture Notes
- ESM module (`import`/`export`) with `__dirname` emulated via `fileURLToPath`.
- Cache is version-scoped and SHA256-verified to prevent stale/corrupted artifacts.
- Multi-URL fallback pattern handles GitHub repo renames (vadimcn/vscode-lldb → vadimcn/codelldb).
- VSIX files are ZIP archives; `extractZip` from `extract-zip` package handles extraction.
- `cacheWritable` is a module-level mutable flag set in `main()` — ordering dependency exists.