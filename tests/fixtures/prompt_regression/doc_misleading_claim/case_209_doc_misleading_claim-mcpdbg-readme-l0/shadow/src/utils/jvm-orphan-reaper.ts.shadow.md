# src\utils\jvm-orphan-reaper.ts
@source-hash: bd86e8299ba4d193
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:04Z

## JVM Orphan Reaper Utility

Detects and kills orphaned debuggee JVM processes left behind by crashed or SIGKILLed mcp-debugger runs. Provides cross-platform enumeration of tagged JVMs and safe cleanup logic.

### Architecture Overview

The module uses a three-property JVM tagging convention stamped via `-D` system properties:
- `-Dmcp.debugger.jvm=true` — marker identifying it as a managed JVM
- `-Dmcp.debugger.owner_pid=<pid>` — PID of the owning mcp-debugger process
- `-Dmcp.debugger.session_tag=<uuid>` — unique session identifier

On startup, caller invokes `reapOrphanJvms()` which lists tagged JVMs, checks owner liveness, and kills orphans whose owner is dead.

### Key Constants (L25-30)

| Constant | Value | Purpose |
|---|---|---|
| `JVM_MARKER` | `-Dmcp.debugger.jvm=true` | Identifies managed JVMs |
| `OWNER_PID_PREFIX` | `-Dmcp.debugger.owner_pid=` | Prefix for owner PID extraction |
| `SESSION_TAG_PREFIX` | `-Dmcp.debugger.session_tag=` | Prefix for session tag extraction |
| `LIST_TIMEOUT_MS` | `5000` | Timeout for OS process listing commands |
| `LIST_MAX_BUFFER` | `10MB` | Max stdout buffer for listing commands |

### Exported Interfaces

- **`TaggedJvm`** (L32-36): `{ pid, ownerPid, sessionTag }` — describes a discovered tagged JVM
- **`ReaperLogger`** (L38-42): Optional logging interface with `info`, `warn`, `error` callbacks
- **`ReapResult`** (L44-49): `{ scanned, killed[], skipped[], errors[] }` — outcome report
- **`ReapOptions`** (L51-58): Config for `reapOrphanJvms` including test seams (`lister`, `isAlive`, `killer` overrides)
- **`SignalFn`** (L232): Injectable signal function type `(pid, signal) => void` for testability

### Core Functions

#### `reapOrphanJvms(opts)` (L60-106) — Main entry point
1. Resolves `lister`/`isAlive`/`killer` from opts or defaults
2. Lists tagged JVMs via `lister()`; catches errors into `result.errors`
3. Skips JVMs where `ownerPid === selfPid` OR `isAlive(ownerPid)` returns true
4. Kills remaining orphans via `killer(jvm.pid)`; logs per kill
5. Returns `ReapResult` with counts and arrays

#### `listTaggedJvms()` (L108-119) — Platform dispatcher
Routes to `listLinux`, `listDarwin`, or `listWindows` based on `process.platform`. Returns `[]` for unsupported platforms.

#### `listLinux()` (L122-146) — Linux JVM lister
Reads `/proc` directory for numeric entries, then reads `/proc/<pid>/cmdline` (NUL-delimited args). Skips disappeared/permission-denied entries. Uses `parseArgs()` to filter.

#### `listDarwin()` (L149-169) — macOS JVM lister
Runs `ps -ww -A -o pid=,command=`. The `-ww` flag prevents truncation of long cmdlines with `-D` markers. Parses `pid command` lines, splits args on whitespace.

#### `listWindows()` (L172-210) — Windows JVM lister
Runs PowerShell `Get-CimInstance Win32_Process` (modern, not deprecated `wmic`) with `-NoProfile` for speed. Parses JSON output (handles both single-object and array cases). Whitespace-splits command line — safe for `-D` args which contain no unescaped whitespace.

#### `parseArgs(pid, args)` (L213-229) — Arg parser
Scans argument array for `JVM_MARKER`, `OWNER_PID_PREFIX`, `SESSION_TAG_PREFIX`. Returns `TaggedJvm | null`. Returns null if marker absent or `ownerPid <= 0`.

#### `isPidAlive(pid, signal?)` (L236-248) — Liveness check
Uses `signal(pid, 0)` (the standard POSIX probe). Returns `true` for `EPERM` (process exists, no permission). Returns `false` for `ESRCH` or other errors. Guards `pid <= 0`.

#### `defaultKill(pid, signal?)` (L251-260) — Kill with error classification
Sends `SIGKILL` (maps to `TerminateProcess` on Windows via Node). Returns `false` (not `true`) for `ESRCH` (already gone) and `EPERM` (different user). Re-throws unknown errors.

### Test Seam Design
All platform calls are injectable via `ReapOptions` (`lister`, `isAlive`, `killer`) and `SignalFn` parameter on `isPidAlive`/`defaultKill`. No monkey-patching of `child_process` needed for tests. Comment at L231 references issue #183.

### Concurrency
`listLinux` uses `Promise.all` over all `/proc` entries for parallel reads. Results are pushed to a shared array from concurrent callbacks — safe in Node.js single-threaded event loop.

### Error Handling Strategy
- Listing failures: caught, appended to `result.errors`, returns early with empty killed/skipped
- Per-JVM kill failures: caught, logged as warn, appended to errors, processing continues
- `ESRCH`/`EPERM` in kill: silently returns `false` (not errors)
- Permission-denied in liveness probe: treated as alive (conservative)