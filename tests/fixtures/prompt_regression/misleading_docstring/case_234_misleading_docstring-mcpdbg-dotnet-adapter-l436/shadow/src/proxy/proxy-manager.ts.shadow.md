# src\proxy\proxy-manager.ts
@source-hash: 174f24ff2d502e3b
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:16Z

## ProxyManager (`src/proxy/proxy-manager.ts`)

### Purpose
Orchestrates debug proxy child processes: spawning, IPC communication, DAP request/response routing, event propagation, lifecycle management, and graceful shutdown.

---

### Key Interfaces & Types

#### `ProxyManagerEvents` (L42–59)
Typed event map for all events emitted by `ProxyManager`:
- DAP lifecycle: `stopped`, `continued`, `terminated`, `exited`
- Proxy lifecycle: `initialized`, `init-received`, `error`, `exit`
- Status/control: `dry-run-complete`, `adapter-configured`, `dap-event`

#### `IProxyManager` (L64–87)
Public contract for proxy managers. Extends `EventEmitter` with typed `on`/`emit`. Key methods:
- `start(config)`, `stop()`
- `sendDapRequest<T>(command, args?, options?)` — generic DAP request
- `isRunning()`, `getCurrentThreadId()`, `setCurrentThreadId()`
- `hasDryRunCompleted()`, `getDryRunSnapshot()`

#### `ProxyRuntimeEnvironment` (L90–93)
Internal interface for injectable module URL and CWD, enabling test isolation.

---

### `ProxyManager` Class (L103–1170)

Extends `EventEmitter`, implements `IProxyManager`.

**Constructor** (L144–157): Accepts `IDebugAdapter | null`, `IProxyProcessLauncher`, `IFileSystem`, `ILogger`, optional `ProxyRuntimeEnvironment`. Installs a no-op `error` listener to prevent unhandled error throws from late IPC messages.

**Private State:**
- `proxyProcess: IProxyProcess | null` — handle to child process
- `sessionId`, `currentThreadId`
- `pendingDapRequests: Map<string, {resolve, reject, command}>` — in-flight DAP requests keyed by UUID
- `isInitialized`, `isStopped`, `isDryRun`, `dryRunCompleteReceived`
- `dapState: DAPSessionState | null` — functional core mirror (observability only; `pendingDapRequests` Map is authoritative)
- `stderrBuffer: string[]` — bounded (100 lines) stderr capture for error reporting
- `lastExitDetails` — snapshot of exit code/signal/stderr at process exit
- `activeLaunchBarrier: AdapterLaunchBarrier | null` — adapter-specific launch synchronization
- `stopDrainTimeoutMs = 1000`, `defaultDapRequestTimeoutMs = 30000`, `dapParentMarginMs = 5000`
- `exitEmitted` — dedup guard for `exit` event

---

### Key Methods

#### `start(config: ProxyConfig): Promise<void>` (L159–303)
Full proxy startup sequence:
1. Validates no existing proxy process
2. Sets up dry-run/session state
3. Calls `prepareSpawnContext()` → validates env, resolves executable, finds proxy script
4. Launches proxy via `proxyProcessLauncher.launchProxy()`
5. Validates PID presence
6. Calls `setupEventHandlers()`
7. 50ms settle delay, then `sendInitWithRetry(initCommand)`
8. Returns Promise that resolves on `initialized` or `dry-run-complete`, rejects on `error`/unexpected `exit` (with stderr snippet, capped at 10 lines / 2000 chars)

#### `stop(): Promise<void>` (L305–369)
Graceful shutdown:
1. Calls `drainPendingDapRequests(1000ms)` — polls until in-flight requests settle
2. Re-checks `proxyProcess` (may have been nulled by concurrent exit)
3. Sets `isStopped = true`, calls `cleanup()`
4. Sends `{cmd: 'terminate'}` IPC message if not already killed
5. Waits up to 5s for exit, then `SIGKILL`

#### `sendDapRequest<T>(command, args?, options?)` (L396–490)
Sends a DAP command over IPC with UUID tracking:
- Checks `isInitialized`; throws if not
- Optionally creates `AdapterLaunchBarrier` via `adapter.createLaunchBarrier()`
- **Fire-and-forget path** (L417–437): if `barrier && !barrier.awaitResponse`, sends command and awaits barrier instead of response; returns `{} as T`
- **Normal path**: registers resolve/reject in `pendingDapRequests`, mirrors into `dapState`, sends command
- **Timeout**: parent backstop = `(options.timeoutMs ?? 30000) + 5000ms`; worker timeout fires first producing the actionable error

#### `prepareSpawnContext(config)` (L504–542)
Resolves executable path (via adapter or config), finds proxy bootstrap script, clones `process.env`. Throws if no executable path available.

#### `findProxyScript()` (L554–587)
Locates `proxy-bootstrap.js` relative to this module's `import.meta.url`. Three layout cases:
- `moduleDir` ends in `dist/` → `dist/proxy/proxy-bootstrap.js`
- `moduleDir` ends in `dist/proxy/` → `proxy-bootstrap.js` (sibling)
- Fallback → `../../dist/proxy/proxy-bootstrap.js` (dev layout)

#### `sendInitWithRetry(initCommand)` (L589–664)
Retries init IPC send up to 6 times (5 retries) with exponential backoff `[500, 1000, 2000, 4000, 8000]ms`. Awaits `init-received` event per attempt. On exhaustion, throws with exit details + stderr snippet.

#### `setupEventHandlers()` (L722–798)
Wires all IPC/process events:
- `message` → `handleProxyMessage()`
- `ipc-send-start/complete/failed/error` → debug/warn logging
- `stderr` data → `LineBuffer` → `recordStderrLines()` (line-buffered to prevent secret straddle, issue #151)
- stderr `end`/`close` → flush `LineBuffer`
- `exit` → `handleProxyExit()`
- `error` → emit `error`, `cleanup()`

#### `handleProxyMessage(rawMessage)` (L827–929)
Central IPC message dispatcher:
1. Drops messages if `isStopped`
2. Silently handles `ipc-heartbeat` and `ipc-heartbeat-tick` messages
3. Validates via `isValidProxyMessage()`
4. **Fast-path**: `dapEvent` messages → `handleDapEvent()` immediately (avoids missed stops)
5. `status` messages → `handleStatusMessage()`
6. Runs `handleProxyMessage()` from functional core → executes returned commands (`log`, `emitEvent`, `killProcess`, `sendToProxy`)
7. Syncs `isInitialized`, `adapterConfigured`, `currentThreadId` from `result.newState`
8. `dapResponse` → `handleDapResponse()`
- Note: `emitEvent` commands for `dapEvent` type are skipped (already handled by fast-path, L886)

#### `handleDapResponse(message)` (L931–970)
Resolves/rejects pending Promise from `pendingDapRequests`. On success with `threads` command, opportunistically captures `threads[0].id` as `currentThreadId`. Resolves with `message.response || message.body`.

#### `handleDapEvent(message)` (L972–1008)
Routes DAP events to typed emits. Notifies `activeLaunchBarrier`. Special cases: `stopped` (captures threadId, emits with undefined if absent), `continued`, `terminated`, `exited`; all others → `dap-event`.

#### `handleStatusMessage(message)` (L1010–1065)
Routes proxy status strings:
- `proxy_minimal_ran_ipc_test` → kill process
- `init_received` → emit `init-received`
- `dry_run_complete` → update snapshots, emit `dry-run-complete`
- `adapter_configured_and_launched` → `adapterConfigured = true`, emit `adapter-configured`, conditionally emit `initialized`
- `adapter_connected` → conditionally emit `initialized`
- `adapter_exited` | `dap_connection_closed` | `terminated` → emit `exit` (deduplicated via `exitEmitted`)

#### `handleProxyExit(code, signal)` (L1067–1097)
Handles process exit: synthesizes `dry-run-complete` if dry run exited clean without reporting, rejects all pending requests, emits `exit` (deduplicated), calls `cleanup()`.

#### `cleanup()` (L1099–1131)
Cancels all pending requests, clears functional core mirror, disposes `activeLaunchBarrier`, disposes adapter (releases AdapterRegistry slot), nulls `proxyProcess`, resets all state flags.

#### `recordStderrLines(lines)` (L805–825)
Sanitizes and logs stderr lines. Pre-init: appends to bounded (100-line) `stderrBuffer`. Post-exit: also appends to `lastExitDetails.capturedStderr` (also bounded at 100).

#### `drainPendingDapRequests(timeoutMs, pollIntervalMs=20)` (L378–394)
Polling wait for `pendingDapRequests` to empty. `isStopped` remains false during drain so IPC responses continue resolving Promises.

---

### Architectural Decisions
- **Dual-layer state**: `pendingDapRequests` Map is authoritative for promise resolution; `dapState` (functional core) is a mirror for observability only (L452–460, L941–944)
- **Fire-and-forget barrier path**: adapters can opt out of awaiting DAP responses by returning `!barrier.awaitResponse`; `ProxyManager` awaits `barrier.waitUntilReady()` instead (L417–437)
- **Exit event deduplication**: `exitEmitted` flag prevents double-emission from both `handleStatusMessage` and `handleProxyExit` (L1059–1062, L1090–1093)
- **Line-buffered stderr**: `LineBuffer` prevents secret/credential straddle leaks across chunk boundaries (L760–769)
- **Parent backstop timeout**: DAP request timeout = worker timeout + 5000ms margin, so worker's error fires first (L475–488)
- **Late error safety**: no-op `error` listener in constructor prevents Node.js unhandled error throws from late IPC (L156)
