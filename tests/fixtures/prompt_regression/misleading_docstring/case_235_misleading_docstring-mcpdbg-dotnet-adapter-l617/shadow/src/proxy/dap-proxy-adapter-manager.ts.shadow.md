# src\proxy\dap-proxy-adapter-manager.ts
@source-hash: 27105d55906901a6
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:20Z

## Purpose
Provides language-agnostic debug adapter process lifecycle management for the DAP proxy: spawning, stream handling, and graceful shutdown of any debug adapter child process.

## Key Exports

### `GenericAdapterConfig` interface (L19-25)
Configuration shape for spawning any debug adapter:
- `command`: executable path/name
- `args`: command-line arguments
- `logDir`: directory for adapter logs (created if missing)
- `cwd?`: optional working directory (inherited from parent if omitted)
- `env?`: optional environment variables (falls back to `process.env`)

### `GenericAdapterManager` class (L30-262)
Core class managing adapter process lifecycle. Constructor accepts:
- `processSpawner: IProcessSpawner` — abstracted process spawning (enables testability)
- `logger: ILogger` — structured logging interface
- `fileSystem: IFileSystem` — abstracted FS operations
- `platform: NodeJS.Platform` (optional, default `globalThis.process.platform`) — overridable for tests (issue #183)

#### `ensureLogDirectory(logDir)` (L42-51)
Delegates to `fileSystem.ensureDir(logDir)`. Wraps errors with descriptive message. Called automatically by `spawn()`.

#### `spawn(config)` (L56-138) → `Promise<AdapterSpawnResult>`
Main public method. Flow:
1. Calls `ensureLogDirectory` (L60)
2. Builds `spawnOptions` with `stdio: ['ignore', 'pipe', 'pipe']`, `detached: true`, `windowsHide: true` (L67-72)
3. Conditionally sets `cwd` only if provided (L74-77)
4. Logs critical env vars (`NODE_OPTIONS`, `NODE_DEBUG`, `NODE_ENV`, `DEBUG`, `VSCODE_INSPECTOR_OPTIONS`) via `sanitizeStderr` redaction (L84-96)
5. Calls `processSpawner.spawn()` (L114)
6. Validates PID existence (L116-118)
7. Calls `adapterProcess.unref()` so proxy lifecycle is not blocked (L121-126)
8. Calls `setupProcessHandlers()` (L132)
9. Returns `{ process, pid }` (L134-137)

#### `shutdown(process, options)` (L201-261) → `Promise<void>`
Graceful shutdown with PID-reuse safety:
- Guards: null process/pid → no-op (L202-205)
- Guards: already-exited process (`exitCode !== null || signalCode !== null`) → no-op (L210-213)
- **Windows tree-kill path** (L217, L226-235): when `options.killProcessTree === true` AND `platform === 'win32'`, runs `taskkill /PID <pid> /T /F` **first** (before any SIGTERM) to kill grandchildren (e.g., rdbg-spawned debuggee). Rationale: `taskkill /T` can only discover children while parent is alive (issue #156).
- **Unix path**: sends `SIGTERM`, waits 300ms, escalates to `SIGKILL` if process hasn't exited (L237-253)
- Escalation logic uses an `exit` event listener (`exited` flag, L222-223) rather than `process.killed` (which only indicates signal was sent, not actual exit)

#### `setupProcessHandlers(adapterProcess)` — private (L143-170)
Registers:
- `error` event → logs spawn errors
- `stderr` via `consumeStream` → logs at `error` level with `[AdapterManager STDERR]` prefix
- `stdout` via `consumeStream` → logs at `debug` level with `[AdapterManager STDOUT]` prefix (drained to prevent pipe buffer stall)
- `exit` event → logs exit code/signal

#### `consumeStream(stream, logLine)` — private (L178-189)
Line-buffers a `Readable` stream using `LineBuffer`, then sanitizes via `sanitizeStderr` before passing to `logLine`. Key design: partial lines flushed on `end`/`close` (not on process `exit`) to prevent straddle secret leakage across chunk boundaries (issues #151/#153). Empty/whitespace lines are filtered before sanitization.

## Dependencies
- `@debugmcp/shared`: `LineBuffer` (line buffering), `sanitizeStderr` (secret/token redaction)
- `./dap-proxy-interfaces.js`: `IProcessSpawner`, `ILogger`, `IFileSystem`, `AdapterSpawnResult`
- Node.js `child_process.ChildProcess`, `stream.Readable`

## Key Architectural Decisions
- **Detached + unref**: adapter process runs independently; proxy exit does not kill adapter (L70-71, L121-126)
- **Windows tree-kill must be first strike**: `taskkill /T` only works while parent is alive; never use as fallback (L192-199 docstring, issue #156)
- **PID-reuse guard**: checks `exitCode`/`signalCode` before any kill to avoid signaling an unrelated process that reused the PID (L210-213)
- **Sanitization at line boundary**: `LineBuffer` + `sanitizeStderr` prevents secrets split across TCP chunks from leaking (issues #151/#153)
- **`cwd` inheritance**: explicitly not set unless provided, inheriting from parent process (L74-77)