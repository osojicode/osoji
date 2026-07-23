# src\proxy\dap-proxy-worker.ts
@source-hash: 9eb11a385c29748e
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:35:19Z

## DapProxyWorker — Core DAP Proxy Worker

### Purpose
Orchestrates the full lifecycle of a Debug Adapter Protocol (DAP) proxy session: initialization, adapter spawning/connection, protocol message routing, event forwarding, and graceful shutdown. Uses the **Adapter Policy pattern** (`AdapterPolicy` from `@debugmcp/shared`) to eliminate language-specific hardcoding.

---

### Key Types

#### `DapProxyWorkerHooks` (L44-56)
Optional hook overrides for testing/customization:
- `exit?: (code) => void` — replaces `process.exit` on fatal errors (defaults to `process.exit`)
- `createTraceFile?: (sessionId, logDir) => string | undefined` — configures per-session DAP frame tracing; default writes `dap-trace-{sessionId}.ndjson` and sets `process.env.DAP_TRACE_FILE`

---

### `DapProxyWorker` class (L58-1076)

#### Key Fields
| Field | Type | Purpose |
|---|---|---|
| `state` | `ProxyState` | State machine: `UNINITIALIZED → INITIALIZING → CONNECTED → SHUTTING_DOWN → TERMINATED` |
| `adapterPolicy` | `AdapterPolicy` | Language-specific behavior (default: `DefaultAdapterPolicy`) |
| `adapterState` | `AdapterSpecificState` | Policy-managed per-session mutable state |
| `commandQueue` | `(DapCommandPayload \| SilentDapCommandPayload)[]` | Queue for adapters requiring command queueing (e.g. js-debug) |
| `preConnectQueue` | `DapCommandPayload[]` | Holds DAP commands arriving before connection is established |
| `isAttachMode` | `boolean` | Drives attach vs. launch handshake and shutdown behavior |
| `deferInitializedHandling` | `boolean` | Set for Go/Java/attach flows to avoid `initialized` event race |
| `requestTracker` | `CallbackRequestTracker` | Tracks in-flight DAP requests with timeout callbacks |
| `processManager` | `GenericAdapterManager` | Spawns/kills the adapter subprocess |
| `connectionManager` | `DapConnectionManager` | Manages TCP DAP client, session init, breakpoints, disconnect |

#### Constructor (L84-103)
- Instantiates `CallbackRequestTracker` with `handleRequestTimeout` callback
- Resolves `exitHook` (default: `process.exit`) and `traceFileFactory` (default: writes NDJSON trace file + sets env var)
- Initializes `adapterState` from `DefaultAdapterPolicy.createInitialState()`

---

### Core Methods

#### `handleCommand(command: ParentCommand)` (L159-195) — **Public**
Main dispatch loop. Routes `cmd` to:
- `'init'` → `handleInitCommand`
- `'dap'` → `handleDapCommand`  
- `'terminate'` → `handleTerminate`

Sets `currentSessionId` from command. Catches errors and sends error message upstream.

#### `handleInitCommand(payload: ProxyInitPayload)` (L200-294) — **Public**
Full initialization sequence:
1. Idempotent guard: if `INITIALIZING`, acks and returns; throws if not `UNINITIALIZED`
2. Sends `'init_received'` status
3. Validates payload via `validateProxyInitPayload`
4. Selects adapter policy via `selectAdapterPolicy(language, adapterCommand)`
5. Creates logger, optional trace file, `GenericAdapterManager`, `DapConnectionManager`
6. On `dryRunSpawn`: calls `handleDryRun` and returns
7. Otherwise calls `startAdapterAndConnect`
8. On error: resets to `UNINITIALIZED`, sends error, calls `shutdown()`, then `exitHook(1)` via deferred timers (to flush IPC)

#### `handleTerminate()` (L942-969) — **Public**
Idempotent. In attach mode + CONNECTED: sends DAP disconnect with `terminateDebuggee=false` first (preserves debuggee), then calls `shutdown()`. Sends `'terminated'` status.

#### `shutdown()` (L974-1030) — **Public**
Shutdown sequence:
1. Guards against re-entry
2. Clears request tracker
3. DAP disconnect (`terminateDebuggee = !isAttachMode`)
4. Calls `dapClient.shutdown('worker shutdown')`
5. Waits 500ms for adapter cleanup (both modes)
6. Kills adapter process (`killProcessTree: !isAttachMode` — tree-kill only for launch mode to avoid killing pre-existing debuggee in attach mode)

#### `getState()` (L152-154) — **Public**
Returns current `ProxyState` (primarily for testing).

---

### Private Methods

#### `selectAdapterPolicy(language?, adapterCommand?)` (L108-147)
Policy selection priority:
1. `language` field → `getPolicyForLanguage()` (if not DefaultAdapterPolicy)
2. No `adapterCommand` → fallback to `PythonAdapterPolicy` (pre-monorepo legacy)
3. Command shape matching via `*.matchesAdapter(adapterCommand)` against all known policies
4. Final fallback: `DefaultAdapterPolicy`

#### `startAdapterAndConnect(payload)` (L347-554)
- Gets `spawnConfig` from `adapterPolicy.getAdapterSpawnConfig()`
- **Spawn mode**: spawns adapter via `processManager.spawn()`, wires `error`/`exit` events, sends `'adapter_exited'` status
- **Connect mode**: no process, connects directly to external DAP server
- Connects via `connectionManager.connectWithRetry(host, port)`
- Detects attach mode from `launchConfig.request === 'attach'` or `__attachMode`
- **Branching on adapter initialization behavior**:
  - `requiresCommandQueueing()` → CONNECTED immediately, drain pre-connect queue
  - `sendAttachBeforeInitialized` + attach → sends attach first, races on `initializedEventPromise`, then `handleInitializedEvent()`
  - Standard attach → waits for `initialized`, sends attach, then `handleInitializedEvent()`
  - `sendLaunchBeforeConfig` (Go/Java) → two-phase: brief wait (2s), launch, wait for initialized
  - Default launch (Python/others) → sends launch, waits for `initialized` via event handler

#### `setupDapEventHandlers()` (L559-650)
Wires DAP events through `connectionManager.setupEventHandlers`. Key behaviors:
- `onInitialized`: if command-queueing policy → forward event + drain queue; if deferred → signal promise; else → `handleInitializedEvent()`
- `onStopped`: auto-discovers missing `threadId` via `threads` request; Java policy pre-fetches threads regardless (L610-619)
- `onTerminated`: forwards event, calls `shutdown()`
- `onClose`: sends `'dap_connection_closed'`, calls `shutdown()`

#### `handleInitializedEvent()` (L655-705)
Sets initial breakpoints (grouped by resolved file path), sends `configurationDone`, transitions to `CONNECTED`, sends `'adapter_configured_and_launched'`. Idempotent via `initializedEventHandled` flag.

#### `handleDapCommand(payload: DapCommandPayload)` (L710-820)
- If no `dapClient` and `INITIALIZING`: queues to `preConnectQueue`
- Consults `adapterPolicy.shouldQueueCommand()` → may queue to `commandQueue` (with optional injected silent `configurationDone`)
- Otherwise: tracks request, optionally injects `runtimeExecutable`, sends via `dapClient.sendRequest()`
- Calls `adapterPolicy.updateStateOnCommand/Response` hooks
- On `launch`/`attach`: may trigger `ensureInitialStop()`

#### `drainCommandQueue()` (L825-882)
- Applies `adapterPolicy.processQueuedCommands()` for ordering
- Processes each command: silent commands skip response; normal commands track, send, respond
- Triggers `ensureInitialStop()` after `launch`/`attach` if policy requires it

#### `drainPreConnectQueue()` (L916-924)
Replays `preConnectQueue` through `handleDapCommand` after connection established.

#### `ensureInitialStop(timeoutMs=12000)` (L887-911)
Polls `threads` request in a loop until a valid thread is found, then sends `pause`. Used for JS-debug initial stop behavior.

#### `handleDryRun(payload)` (L300-342)
Gets spawn config, logs the would-be command, sends `'dry_run_complete'` status with command/script info, transitions to `TERMINATED`, calls `exitHook(0)` after deferred timers.

---

### Message Sending Helpers (L1032-1075)
All delegate to `dependencies.messageSender.send()`:
- `sendStatus(status, extra?)` → `StatusMessage` with `type: 'status'`
- `sendDapResponse(requestId, success, response?, error?)` → `DapResponseMessage` with `type: 'dapResponse'`
- `sendDapEvent(event, body)` → `DapEventMessage` with `type: 'dapEvent'`
- `sendError(message)` → `ErrorMessage` with `type: 'error'`

---

### Architectural Decisions
- **Adapter Policy pattern**: All language-specific behavior delegated to `AdapterPolicy` objects from `@debugmcp/shared`; no hardcoded language names in core logic (except the `'java'` name check in `onStopped` at L610)
- **IPC flush via setImmediate+setTimeout(100ms)**: Used in both dry-run and init error paths to ensure IPC messages reach parent before process exit (especially important on Windows)
- **Silent `configurationDone` injection**: When `deferConfigDone` is set in init behavior, a synthetic `configurationDone` command (L739-748) is injected before queued user commands
- **Idempotent shutdown/terminate**: Guards on state prevent double-shutdown from concurrent paths
- **Kill tree only in launch mode**: `killProcessTree: !isAttachMode` prevents killing a pre-existing debuggee in attach scenarios (L1024)
- **`attachRequest` not awaited before `handleInitializedEvent`**: In attach-first mode, the attach response race allows `configurationDone` to unblock the adapter (line 469-472)