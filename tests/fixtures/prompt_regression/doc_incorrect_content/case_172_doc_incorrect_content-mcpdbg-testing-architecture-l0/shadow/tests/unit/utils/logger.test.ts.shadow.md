# tests\unit\utils\logger.test.ts
@source-hash: e6a8cd11ccb8e9cb
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:20Z

## Purpose
Unit test suite for `src/utils/logger.ts` — validates logger creation behavior, file transport caching, stale log file cleanup, environment-based configuration, and error suppression.

## Structure
Two top-level `describe` blocks:
- **`logger utility`** (L43–239): Tests `createLogger()` and `getLogger()` using a fully mocked `winston` module.
- **`cleanupStaleLogFiles`** (L241–338): Tests `cleanupStaleLogFiles()` using real filesystem I/O in a temp directory.

## Winston Mock (L6–36)
Entire `winston` module is mocked via `vi.mock('winston', ...)`. Three spies are exposed at module level:
- `consoleTransportSpy` (L6): Captures `new transports.Console(options)` calls; stamps `this.type = 'console'`
- `fileTransportSpy` (L10): Captures `new transports.File(options)` calls; stamps `this.type = 'file'`
- `createLoggerSpy` (L14): Returns `{ on: vi.fn(), warn: vi.fn() }` by default

The mock's `Console` and `File` constructors (L22–27) call the respective spies via `.call(this, options)` to preserve constructor context so `this.type` is set on the constructed instance — enabling transport identity checks in tests.

## Module State Isolation (L44–53)
Each test in `logger utility` runs:
1. `vi.resetModules()` — discards the cached `logger.js` module
2. `await import('../../../src/utils/logger.js')` — re-imports fresh, resetting per-process state (file transport cache, stale-log cleanup latch, default logger)

This is critical because the logger module holds per-process singleton state.

## Helper: `stubFs` (L61–66)
Stubs `fs.existsSync`, `fs.mkdirSync`, `fs.readdirSync` to prevent real disk I/O during `createLogger` tests. Default: `dirExists = true` (no mkdir called).

## Key Test Cases — `createLogger`

| Test | Line | What it validates |
|---|---|---|
| Default transports | L68–83 | Both console and file transports created; no mkdir when dir exists |
| Default filename | L85–92 | File uses `debug-mcp-server-<pid>.log` pattern |
| Explicit file path | L94–102 | Verbatim path used if `file` option provided |
| File transport reuse | L104–119 | Same path → same transport instance reused (singleton per path) |
| Distinct paths | L121–128 | Different explicit paths → separate File transport instances |
| Stale-log cleanup once | L130–139 | `readdirSync` called once for default path, never for explicit path |
| Container mode | L141–153 | `MCP_CONTAINER=true` → `/app/logs/debug-mcp-server.log`, no pid cleanup |
| mkdir failure + console | L155–168 | `console.error` called with "Failed to ensure log directory" |
| mkdir failure + silenced | L170–182 | `CONSOLE_OUTPUT_SILENCED=1` → no console transport, no console.error |
| `getLogger` fallback | L184–201 | Fallback logger created at `info` level with namespace `debug-mcp:default-fallback`; warns once |
| Transport error logged | L203–221 | Logger `on('error')` handler calls `console.error` with message |
| Transport error silenced | L223–238 | `CONSOLE_OUTPUT_SILENCED=1` → error handler does not call console.error |

## Helper: `makeAgedFile` (L256–262)
Creates a real file in `tmpDir` with `fs.utimesSync` to backdate its mtime/atime by `ageMs`.

## Helper: `throwingSignal` (L265–271)
Returns a function that throws a `NodeJS.ErrnoException` with a specified code. Used to mock `process.kill(pid, 0)` behavior in `cleanupStaleLogFiles`.

## Key Test Cases — `cleanupStaleLogFiles`

| Test | Line | What it validates |
|---|---|---|
| Dead PID + old file deleted | L273–279 | ESRCH → delete file aged > 1 week |
| Own PID never deleted | L281–287 | Current `process.pid` file never deleted regardless of age |
| EPERM → keep file | L289–295 | Process alive (no permission) → skip deletion |
| Signal succeeds → keep file | L297–303 | Process alive (no error) → skip deletion |
| Recent dead PID kept | L305–311 | File < 1 week old, even if PID dead → keep |
| Non-pid files untouched | L313–323 | Container log, proxy session log, other files never touched |
| Custom maxAgeMs | L325–331 | `maxAgeMs: 1000` → deletes 5-second-old file |
| Nonexistent directory | L333–337 | Does not throw |

## Environment Variables Tested
- `MCP_CONTAINER` (L142): `'true'` → container log path `/app/logs/debug-mcp-server.log`
- `CONSOLE_OUTPUT_SILENCED` (L171, L224): `'1'` → suppress console transport and console.error

## Dependencies
- `vitest`: Test runner with `vi.mock`, `vi.spyOn`, `vi.stubEnv`, `vi.resetModules`
- `fs`, `os`, `path`: Node.js builtins (real in `cleanupStaleLogFiles` suite, spied in `logger utility` suite)
- `winston`: Fully mocked; never imported for real
- Module under test: `../../../src/utils/logger.js` (re-imported per test for isolation)

## Invariants Verified
1. File transport singleton per path — one file handle, one byte counter (issue #121 referenced at L111)
2. Stale-log cleanup runs at most once per process (latch pattern)
3. Cleanup only targets `debug-mcp-server-<numeric-pid>.log` filename pattern
4. Own process PID file is always preserved
5. Container mode uses a fixed single filename (no PID in name), no stale-log scan