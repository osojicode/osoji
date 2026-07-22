# src\proxy\proxy-manager.ts
@source-hash: 174f24ff2d502e3b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:37Z

## ProxyManager (src/proxy/proxy-manager.ts)

### Purpose
Orchestrates spawning and IPC communication with a child debug proxy process. Acts as the bridge between the MCP server's DAP session logic and the isolated proxy worker. Manages proxy lifecycle (spawn, init, stop), DAP request routing (send/resolve/reject), and event forwarding (stopped, continued, terminated, etc.).

---

### Key Interfaces & Types

**`ProxyManagerEvents` (L42–59)** — Typed event map for all events emitted by `ProxyManager`:
- DAP events: `stopped`, `continued`, `terminated`, `exited`
- Lifecycle: `initialized`, `init-received`, `error`, `exit`
- Status: `dry-run-complete`, `adapter-configured`, `dap-event`

**`IProxyManager` (L64–87)** — Public contract: `start`, `stop`, `sendDapRequest`, `isRunning`, `getCurrentThreadId`, `setCurrentThreadId`, `hasDryRunCompleted`, `getDryRunSnapshot`, typed `on`/`emit`.

**`ProxyRuntimeEnvironment` (L90–93)** — Internal interface abstracting `import.meta.url` and `process.cwd()` for testability.

---

### Class: `ProxyManager` (L103–1170)

Extends `EventEmitter`, implements `IProxyManager`.

#### Constructor (L144–157)
- Accepts: `adapter: IDebugAdapter | null`, `proxyProcessLauncher: IProxyProcessLauncher`, `fileSystem: IFileSystem`, `logger: ILogger`, optional `runtimeEnv`
- Registers a no-op `'error'` handler to prevent unhandled-error crashes from late IPC messages.

#### Key Private State
| Field | Purpose |
|---|---|
| `proxyProcess` (L104) | Handle to the child proxy process |
| `sessionId` (L105) | Current session identifier |
| `currentThreadId` (L106) | Most recently active DAP thread |
| `pendingDapRequests` (L107–111) | Map of requestId → resolve/reject/command for in-flight DAP requests |
| `isInitialized` (L112) | True once proxy signals it's ready |
| `isStopped` (L113) | Guards message processing after stop() |
| `stopDrainTimeoutMs` (L115) | Max ms to wait for pending DAP requests before force-cancel (1000ms) |
| `defaultDapRequestTimeoutMs` (L117) | Worker-side DAP timeout (30000ms) |
| `dapParentMarginMs` (L122) | Extra parent backstop beyond worker timeout (5000ms) |
| `isDryRun` / `dryRunCompleteReceived` (L123–124) | Dry-run mode tracking |
| `dapState` (L128) | Functional core `DAPSessionState` mirror |
| `stderrBuffer` (L129) | Bounded ring of pre-init stderr lines (max 100) |
| `lastExitDetails` (L130–137) | Snapshot of exit code/signal/stderr for diagnostics |
| `activeLaunchBarrier` (L139) | Optional adapter-provided launch barrier for fire-and-forget DAP sends |
| `exitEmitted` (L142) | Guards against double `exit` event emission |

---

### Key Methods

**`start(config: ProxyConfig): Promise<void>` (L159–303)**
1. Validates no existing proxy process.
2. Calls `prepareSpawnContext()` to resolve executable path and proxy script path.
3. Launches proxy child process via `proxyProcessLauncher.launchProxy()`.
4. Sets up IPC/stderr/exit event handlers via `setupEventHandlers()`.
5. Sends `init` command with retry logic via `sendInitWithRetry()`.
6. Awaits `'initialized'` or `'dry-run-complete'` event (30s timeout).
7. On exit before init, embeds last 10 stderr lines (capped at 2000 chars) in error.

**`stop(): Promise<void>` (L305–369)**
1. Drains in-flight DAP requests up to `stopDrainTimeoutMs` (1000ms).
2. Sets `isStopped = true`, calls `cleanup()`.
3. Sends `{ cmd: 'terminate' }` to proxy via IPC.
4. Waits up to 5s for graceful exit, then `SIGKILL`.

**`sendDapRequest<T>(command, args?, options?): Promise<T>` (L396–490)**
- Requires `proxyProcess` non-null and `isInitialized = true`.
- Optionally creates an `AdapterLaunchBarrier` via `adapter.createLaunchBarrier()`.
- **Fire-and-forget path** (L417–437): If barrier exists and `barrier.awaitResponse` is false, sends command, sets barrier, awaits `barrier.waitUntilReady()`, returns `{}`.
- **Normal path** (L445–489): Registers promise in `pendingDapRequests`, mirrors into `dapState`, sends command. Parent backstop timeout = `(options.timeoutMs ?? 30000) + 5000ms`.

**`setupEventHandlers(): void` (L722–798)**
- Wires `message`, `ipc-send-start`, `ipc-send-complete`, `ipc-send-failed`, `ipc-send-error` events on proxy process.
- Creates a scoped `LineBuffer` for stderr line-buffering; flushes on stream `end`/`close` (not process `exit`) to prevent straddle leaks across split chunks.
- Handles process `exit` and `error`.

**`handleProxyMessage(rawMessage): void` (L827–929)**
- Guards against `isStopped` (late messages after stop).
- Silently discards `ipc-heartbeat` and `ipc-heartbeat-tick` messages.
- Fast-paths `dapEvent` type directly to `handleDapEvent()` before feeding functional core.
- Runs `handleProxyMessage()` from `dap-core` to get commands array + new state.
- Executes commands: `log`, `emitEvent` (skipped for dapEvent, already handled), `killProcess`, `sendToProxy`.
- Syncs `isInitialized`, `adapterConfigured`, `currentThreadId` from new state.
- For `dapResponse` messages, delegates to `handleDapResponse()`.

**`handleDapResponse(message): void` (L931–970)**
- Looks up pending request by `requestId`.
- Removes from both `pendingDapRequests` and `dapState`.
- Clears active launch barrier if matched.
- On success: opportunistically captures thread ID from `threads` response; resolves with `message.response || message.body`.
- On failure: rejects with `message.error` or generic string.

**`handleDapEvent(message): void` (L972–1008)**
- Notifies `activeLaunchBarrier` via `onDapEvent()`.
- Dispatches: `stopped` → emits with threadId/reason; `continued`, `terminated`, `exited` → emits directly; default → `dap-event` generic.

**`handleStatusMessage(message): void` (L1010–1065)**
- `proxy_minimal_ran_ipc_test`: kills proxy (IPC test mode).
- `init_received`: emits `init-received`.
- `dry_run_complete`: captures command/script snapshots, emits `dry-run-complete`.
- `adapter_configured_and_launched`: sets `adapterConfigured`, emits `adapter-configured`, marks initialized.
- `adapter_connected`: marks initialized.
- `adapter_exited` / `dap_connection_closed` / `terminated`: emits `exit` (once, guarded by `exitEmitted`).

**`handleProxyExit(code, signal): void` (L1067–1097)**
- Notifies/clears active launch barrier.
- Synthesizes `dry-run-complete` if dry run proxy exited cleanly without reporting.
- Rejects all pending DAP requests with `'Proxy exited'`.
- Emits `exit` (guarded by `exitEmitted`).
- Calls `cleanup()`.

**`cleanup(): void` (L1099–1131)**
- Rejects and clears all `pendingDapRequests`.
- Clears functional core mirror via `clearPendingRequests()`.
- Clears launch barrier.
- Calls `adapter.dispose()` (releases AdapterRegistry slot), nulls `adapter`.
- Resets all instance fields to initial state.

**`prepareSpawnContext(config): Promise<{executablePath, proxyScriptPath, env}>` (L504–542)**
- Validates adapter environment via `adapter.validateEnvironment()`.
- Resolves executable path via `adapter.resolveExecutablePath()` if not provided.
- Finds proxy bootstrap script via `findProxyScript()`.
- Clones `process.env` (omitting `undefined` values).

**`findProxyScript(): Promise<string>` (L554–587)**
- Derives proxy bootstrap path from `import.meta.url`.
- Handles 3 layout cases: `dist/` root, `dist/proxy/`, or dev fallback `../../dist/proxy/proxy-bootstrap.js`.
- Throws descriptive error with build instructions if not found.

**`sendInitWithRetry(initCommand): Promise<void>` (L589–664)**
- Up to 6 attempts (0–5), with exponential backoff: `[500, 1000, 2000, 4000, 8000]` ms.
- Awaits `init-received` event with per-attempt timeout; returns on first acknowledgment.
- On final failure, includes `lastExitDetails` (code/signal/stderr) in error.

**`drainPendingDapRequests(timeoutMs, pollIntervalMs): Promise<void>` (L378–394)**
- Polls every 20ms up to `timeoutMs`; logs warning if requests remain after deadline.

**`recordStderrLines(lines): void` (L805–825)**
- Sanitizes lines via `sanitizeStderr()`, logs each at error level.
- Pre-init: bounded ring buffer of max 100 lines.
- After exit snapshot: also appended to `lastExitDetails.capturedStderr` (also max 100).

**`setActiveLaunchBarrier / clearActiveLaunchBarrier` (L1133–1155)** — Safe disposal-guarded barrier management.

**`hasDryRunCompleted(): boolean` (L1157–1159)**, **`getDryRunSnapshot()` (L1161–1169)** — Dry-run state accessors.

---

### Architecture Notes
- **Hybrid imperative/functional core**: `handleProxyMessage` calls `dap-core/handleProxyMessage` for state transitions and command derivation, but retains imperative Promise resolution for DAP requests (cannot be expressed as pure commands).
- **Double-emission guard**: `exitEmitted` flag prevents `exit` being emitted from both `handleStatusMessage` (status-level termination) and `handleProxyExit` (OS-level exit).
- **Stderr straddle protection**: `LineBuffer` is scoped per process instance; flushed on stream `end`/`close` not process `exit` to handle pipe-drain ordering.
- **Parent backstop timeout**: DAP request timeout = worker timeout + 5000ms; worker fires first, producing the actionable error message.
- **Drain on stop**: 1000ms window for in-flight IPC responses to arrive naturally before cleanup cancels them.
