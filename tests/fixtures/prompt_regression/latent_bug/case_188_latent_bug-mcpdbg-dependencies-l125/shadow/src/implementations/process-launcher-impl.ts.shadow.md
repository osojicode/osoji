# src\implementations\process-launcher-impl.ts
@source-hash: de033a1e03b08d11
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:45Z

## Process Launcher Implementation

Production implementation of `IProxyProcessLauncher` that spawns proxy worker processes via `IProcessManager` and wraps them in a lifecycle-managed `ProxyProcessAdapter`.

### Architecture Overview
- `ProxyProcessLauncherImpl` (L396–467, exported): factory that launches proxy subprocesses with IPC channel
- `ProxyProcessAdapter` (L20–391, internal): adapts `IChildProcess` → `IProxyProcess`, adds deferred initialization protocol, IPC send diagnostics, and safe disposal

---

### ProxyProcessAdapter (L20–391)

Wraps a raw `IChildProcess` and implements `IProxyProcess` via `EventEmitter`. Key design decisions:

**Initialization protocol (L107–373):**
- Initialization promise is created lazily — only when `waitForInitialization()` is first called (L351)
- Watches for incoming `message` events of type `'status'` with `status === 'adapter_configured_and_launched'` or `'dry_run_complete'` (L127–131) to resolve
- Has a configurable timeout (default 30s, L351) that calls `failInitialization()`
- State machine: `'none'` → `'waiting'` → `'completed'` | `'failed'` (L24)
- `handleEarlyExit()` (L211) fires on first `'exit'` event; if state is `'none'`, marks `'failed'` and calls `dispose()`
- Concurrent callers to `waitForInitialization()` while `'waiting'` receive the same promise (L362–364)

**Disposal (L221–242):**
- `dispose()` is idempotent (L222 guard)
- Removes all tracked `childProcessListeners` (L238–241) but intentionally leaves a permanent no-op `'error'` handler on `childProcess` (L85) to suppress late OS/IPC errors after disposal
- Calls `failInitialization()` if waiting (L226–228)

**IPC send (L282–349):**
- `sendCommand()` wraps `send()` with diagnostic events: `'ipc-send-start'`, `'ipc-send-complete'`, `'ipc-send-failed'`, `'ipc-send-error'`
- Accesses `childProcess.channel?.writeQueueSize` (L302–306) via unsafe cast for queue depth metrics
- Throws `Error` if `send()` returns `false` or throws (L321, L347)

**Pass-through properties (L244–270):** `pid`, `stdin`, `stdout`, `stderr`, `killed`, `exitCode`, `signalCode` — all delegate to `childProcess`

---

### ProxyProcessLauncherImpl (L396–467)

Implements `IProxyProcessLauncher`. Constructor takes `IProcessManager` (L398).

**`launchProxy(proxyScriptPath, sessionId, env?)` (L401–466):**
1. Prepends `--trace-uncaught --trace-exit` diagnostic flags to node args (L406–407)
2. Builds `processEnv` from either the caller-supplied `env` or a filtered copy of `process.env` — always strips `NODE_ENV`, `VITEST`, `JEST_WORKER_ID` (L410–430) to prevent proxy from detecting test context
3. Resolves CWD to project root (two dirs above this file) via `fileURLToPath(import.meta.url)` (L434), not `process.cwd()`, ensuring correct IPC and path resolution in VS Code
4. Spawns via `processManager.spawn(process.execPath, args, options)` with `stdio: ['pipe','pipe','pipe','ipc']` and `detached: false` (L448–462)
5. Returns a new `ProxyProcessAdapter` wrapping the child process (L465)

---

### Notable Patterns
- **Deferred promise**: initialization promise is not created until `waitForInitialization()` is called, avoiding unhandled rejection if caller never waits
- **Unhandled rejection suppression**: internal `.catch()` (L152–159) silently absorbs rejections; caller still gets the real rejection when they `await`
- **Belt-and-suspenders env cleanup**: test env vars are filtered in the loop AND explicitly `delete`d after (L428–430)
- **IPC compatibility**: `stdio` typed with `as any` (L449) due to TypeScript not accepting the `'ipc'` tuple form directly
