# scripts\cleanup-test-processes.js
@source-hash: 985f0c152eac6d25
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:28Z

## Purpose
Post-test cleanup script that finds and terminates orphaned MCP-related processes (proxy-bootstrap, dap-proxy, vitest, debugpy) on Unix systems after test suite execution. Skipped on Windows and in CI environments.

## Architecture & Flow

**Entry point logic (L148–160):**
- Runs only when `!process.env.CI && !isWindows` (L148)
- On CI: logs skip message (L153)
- On Windows (non-CI): logs skip message (L155)
- Always prints final banner (L158–160)

**Platform detection (L17–18):**
- `isWindows`: `process.platform === 'win32'`
- `isLinux`: `process.platform === 'linux'` — used only for memory reporting in `cleanup()` (L141–144)

**Project root resolution (L21–23):**
- Uses ESM-compatible `fileURLToPath(import.meta.url)` + `path.dirname` + `path.resolve('..')` to derive `projectRoot`

## Key Functions

### `executeCommand(cmd, silent)` (L31–41)
- Wraps `execSync` with error swallowing. Returns stdout string or `null` on failure.
- `silent=true` uses `stdio: 'pipe'` (captures output); `silent=false` inherits stdio.

### `getProcessList()` (L43–47)
- Runs `ps aux` silently; returns stdout string or `''`.
- Unix-only — not guarded by platform check internally (caller context handles this via `shouldRun`).

### `findMcpProcesses()` (L49–87)
- Escapes `projectRoot` for regex use (L56) to handle paths with special chars.
- Matches 4 patterns (L57–62): `proxy-bootstrap`, `dap-proxy`, `vitest`, `debugpy` — all anchored to `projectRoot` or vice versa.
- Parses `ps aux` output: PID is column index 1 (L72).
- Returns array of `{ pid: number, command: string }` objects.

### `killProcess(pid)` (L89–105)
- Sends `SIGTERM` first, then schedules `SIGKILL` after 100ms via `setTimeout`.
- Returns `true` if `SIGTERM` succeeded (process existed), `false` if it threw (already dead).
- **Note:** `SIGKILL` is fired-and-forgotten asynchronously; the script may exit before it fires for the last process.

### `cleanup()` (L108–145)
- Orchestrates find → log → kill loop.
- Counts killed vs. failed and reports.
- On Linux: runs `free -h | head -2` for memory status.

## Dependencies
- `child_process.execSync` — synchronous shell command execution
- `path`, `url.fileURLToPath` — ESM-compatible `__dirname` shim

## Notable Patterns / Constraints
- ESM module (`import` syntax), run via `#!/usr/bin/env node`.
- All process matching is case-insensitive (`'i'` flag, L67).
- `ps aux` column parsing assumes standard Unix format (USER=0, PID=1).
- No `process.exit()` call; script exits naturally after sync work (async `SIGKILL` timers may not fire).
- CI detection is solely via `process.env.CI` truthiness (L148, L152).