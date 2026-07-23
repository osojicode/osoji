# tests\e2e\npx\npx-test-utils.ts
@source-hash: 1b22ca2729afda74
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:40Z

## NPX E2E Test Utilities

Helper module for end-to-end testing of `@debugmcp/mcp-debugger` via its npm distribution (tarball packaging). Provides lifecycle utilities: build artifact verification, content-hashed pack caching with file-based mutual exclusion, global npm install/uninstall, and MCP client factory for the globally-installed CLI entry.

### Path Constants (L19–L33)
- `ROOT`: Three levels up from this file — workspace root.
- `PACK_LOCK_PATH`: `packages/mcp-debugger/.pack-lock` — advisory lock file for concurrent pack operations.
- `PACK_LOCK_STALE_MS`: 5 minutes — stale lock timeout.
- `PACKAGE_DIR`: `packages/mcp-debugger/`
- `PACKAGE_DIST_DIR`: `packages/mcp-debugger/dist/`
- `PACK_CACHE_DIR`: `packages/mcp-debugger/package-cache/`
- `PACKAGE_JSON_PATH` / `PACKAGE_BACKUP_PATH`: paths for `prepare-pack.js` backup/restore lifecycle.
- `ROOT_DIST_ENTRY`: `dist/index.js` — root workspace TypeScript build output.
- `PACKAGE_DIST_ENTRY`: `packages/mcp-debugger/dist/cli.mjs` — package CLI entry.

### Internal Helpers

**`acquirePackLock()` (L35–66)**: Spin-loop file lock using `wx` (exclusive create) flag on `PACK_LOCK_PATH`. Automatically removes stale locks (older than 5 min). Waits 1 s between retries. Throws on unexpected filesystem errors.

**`releasePackLock()` (L68–77)**: Deletes the lock file; silently ignores `ENOENT`.

**`pathExists(filePath)` (L79–86)**: Returns `true`/`false` via `fs.access`.

**`ensureWorkspaceBuilt()` (L90–103)**: Checks existence of both `ROOT_DIST_ENTRY` and `PACKAGE_DIST_ENTRY`. Throws with actionable message if either is missing. Intentionally does NOT build — build is delegated to `pretest:e2e:npx` npm hook.

**`ensurePackageBackupRestored()` (L105–110)**: Detects leftover `package.json.backup` (from interrupted prepare-pack run) and restores via `node scripts/prepare-pack.js restore`.

**`hashDirectoryContents(dir, hash, relativeTo)` (L112–136)**: Recursively walks a directory, sorting entries deterministically, feeding relative paths and file contents into a SHA-256 hash object.

**`computePackFingerprint()` (L138–143)**: Hashes `package.json` + entire `dist/` directory contents. Returns hex SHA-256 string used as cache key.

**`ensurePackCacheDir()` (L145–147)**: Creates `package-cache/` directory with `recursive: true`.

**`getCachedTarballPath(fingerprint)` (L149–152)**: Returns path `package-cache/<fingerprint>.tgz` if the file exists, else `null`.

**`resolveGlobalCliEntry()` (L269–273)**: Runs `npm root -g` and returns `<globalRoot>/@debugmcp/mcp-debugger/dist/cli.mjs`.

### Exported API

**`NpxTestConfig` (L154–156)**: Interface — optional `logLevel` string.

**`buildAndPackNpmPackage()` (L161–222)**: Main pack lifecycle:
1. Restore any leftover backup, verify workspace built, ensure cache dir exists.
2. Compute fingerprint; return cached tarball if found (pre-lock fast path, L169–173).
3. Acquire file lock; re-check cache after lock (double-checked locking, L181–185).
4. Run `node scripts/prepare-pack.js prepare`, then `npm pack --pack-destination package-cache`.
5. Rename the output tarball to `package-cache/<fingerprint>.tgz`.
6. Always restores `package.json` and releases lock in `finally` block.

**`installPackageGlobally(tarballPath)` (L227–249)**: Uninstalls any existing `@debugmcp/mcp-debugger` globally, installs from tarball path, verifies with `npm list -g`.

**`cleanupGlobalInstall()` (L254–263)**: Uninstalls `@debugmcp/mcp-debugger` globally; swallows all errors (cleanup path).

**`createNpxMcpClient(config)` (L278–387)**: Factory for an MCP client connected to the globally-installed CLI.
- Resolves CLI entry via `resolveGlobalCliEntry()`.
- Spawns via `process.execPath` (avoids Windows `npx.cmd` ENOENT issue, L288 comment).
- Passes `stdio` subcommand, `--log-level`, `--log-file logs/npx-test.log`.
- Monkey-patches `transport.send` (L310–328) and `transport.onmessage` (L343–360) to log all messages to `logs/npx-raw.log` with direction/sequence/timestamp.
- Seeds `client._requestMessageId` with a random offset (L337–338) to avoid ID collisions across parallel test suites.
- Returns `{ client, transport, cleanup }`.

**`getPackageSize(tarballPath)` (L392–401)**: Returns `{ sizeKB, sizeMB }` from `fs.stat`.

**`verifyPackageContents(tarballPath)` (L406–443)**: Runs `tar -tzf` on the tarball. Checks for `javascript`/`js-debug`, `python`/`debugpy`, and `mock` substrings in lowercased output. Gets `bundleSize` from tarball file stat if `package/dist/cli.mjs` is found in listing.

### Architectural Notes
- Uses double-checked locking pattern (L169, L181) to avoid redundant `npm pack` runs under concurrency.
- The `prepare-pack.js` script modifies `package.json` for packing (likely strips workspace protocol deps or sets version), then must be restored — the `finally` block at L211 ensures this even on error.
- Windows compatibility: spawns Node directly (`process.execPath`) rather than `npx` to avoid cmd.exe path resolution failures (L287–291 comment).
- Transport message monkey-patching (L310, L343) is done after `client.connect()` for `onmessage` but before for `send`, meaning outbound messages during connection setup are logged but inbound messages during connect are not captured in the log file.
