# src\utils\jvm-orphan-reaper.ts
@source-hash: bd86e8299ba4d193
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:26Z

## JVM Orphan Reaper Utility

Cross-platform utility that detects and kills orphaned debuggee JVM processes left behind by crashed or SIGKILLed `mcp-debugger` runs. Runs at startup to clean up stale processes before new sessions begin.

### Core Mechanism

Every debuggee JVM is stamped with three `-D` system properties at launch:
- `-Dmcp.debugger.jvm=true` — marker identifying it as owned by mcp-debugger
- `-Dmcp.debugger.owner_pid=<pid>` — PID of the owning mcp-debugger process
- `-Dmcp.debugger.session_tag=<uuid>` — session UUID for traceability

The reaper scans running JVMs, finds tagged ones whose `owner_pid` is no longer alive, and SIGKILLs them. JVMs owned by living processes (concurrent mcp-debugger instances) are skipped.

### Key Interfaces

- **`TaggedJvm` (L32-36)**: `{ pid, ownerPid, sessionTag }` — parsed descriptor for a tagged JVM process.
- **`ReaperLogger` (L38-42)**: Optional logger with `info?`, `warn?`, `error?` callbacks.
- **`ReapResult` (L44-49)**: `{ scanned, killed[], skipped[], errors[] }` — summary returned by `reapOrphanJvms`.
- **`ReapOptions` (L51-58)**: Main configuration for `reapOrphanJvms`; includes `selfPid`, optional `logger`, and test-seam overrides for `lister`, `isAlive`, `killer`.
- **`SignalFn` (L232)**: Injectable signal function type `(pid, signal) => void` to avoid monkey-patching `process.kill` in tests.

### Primary Entry Point

**`reapOrphanJvms(opts: ReapOptions): Promise<ReapResult>` (L60-106)**
1. Resolves `lister`, `isAlive`, `killer` from `opts` or defaults.
2. Calls `lister()` to get all tagged JVMs; on failure, logs warning and returns early with error recorded.
3. For each JVM: skips if `ownerPid === selfPid` (self-guard) or owner is still alive; otherwise kills and records result.
4. Returns `ReapResult` with counts/lists of killed, skipped, and errored JVMs.

### Platform-Specific Listing

**`listTaggedJvms(): Promise<TaggedJvm[]>` (L108-119)**
Dispatcher switching on `process.platform` → `listLinux`, `listDarwin`, `listWindows`; returns `[]` for unknown platforms.

**`listLinux(): Promise<TaggedJvm[]>` (L122-146)**
Reads `/proc` directory, parses each numeric PID's `/proc/<pid>/cmdline` (NUL-delimited args), passes to `parseArgs`. Silently skips disappeared/permission-denied entries.

**`listDarwin(): Promise<TaggedJvm[]>` (L149-169)**
Runs `ps -ww -A -o pid=,command=` (5s timeout, 10MB buffer) to avoid column truncation of long Java cmdlines. Parses `pid command...` lines, splits whitespace for args.

**`listWindows(): Promise<TaggedJvm[]>` (L172-210)**
Runs PowerShell `Get-CimInstance Win32_Process` (modern; avoids deprecated `wmic`) with `-NoProfile` for speed. Parses JSON output; handles both array and single-object results from `ConvertTo-Json`. Defensively type-checks each item's `ProcessId` (number) and `CommandLine` (string).

### Core Helpers

**`parseArgs(pid, args): TaggedJvm | null` (L213-229)**
Scans JVM args for the three marker properties. Returns `null` if `JVM_MARKER` is absent or `ownerPid <= 0`. `sessionTag` is optional (defaults to `''`).

**`isPidAlive(pid, signal?): boolean` (L236-248)**
Sends signal `0` to probe liveness. `EPERM` → alive (process exists, no permission). `ESRCH` or anything else → dead. Guards against `pid <= 0`.

**`defaultKill(pid, signal?): boolean` (L251-260)**
Sends `SIGKILL`. Returns `true` on success, `false` on `ESRCH` (already gone) or `EPERM` (wrong user). Re-throws other errors.

### Constants

| Name | Value | Purpose |
|------|-------|---------|
| `JVM_MARKER` (L25) | `'-Dmcp.debugger.jvm=true'` | Identifies mcp-debugger-owned JVMs |
| `OWNER_PID_PREFIX` (L26) | `'-Dmcp.debugger.owner_pid='` | Prefix for owner PID arg |
| `SESSION_TAG_PREFIX` (L27) | `'-Dmcp.debugger.session_tag='` | Prefix for session UUID arg |
| `LIST_TIMEOUT_MS` (L29) | `5000` | Timeout for external process listing calls |
| `LIST_MAX_BUFFER` (L30) | `10 * 1024 * 1024` | Max stdout buffer for external process listing |

### Design Decisions
- **Dependency injection via `ReapOptions`**: `lister`, `isAlive`, `killer` can be overridden for testing without monkey-patching Node globals (see comment about issue #183).
- **`selfPid` guard (L84)**: Prevents killing JVMs spawned by the current process, and guards against PID recycling where a new process inherits the same PID as a former owner.
- **EPERM handling in `isPidAlive` (L244-245)**: Processes owned by other users that can't be signaled are counted as "alive" and therefore skipped, avoiding unauthorized termination attempts.
- **Windows single-object JSON normalization (L196)**: PowerShell `ConvertTo-Json` outputs a plain object (not array) when only one process matches; the `Array.isArray` check handles both cases.