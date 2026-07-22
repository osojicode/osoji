# src\proxy\dap-proxy-worker.ts
@source-hash: 9eb11a385c29748e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:41Z

## DapProxyWorker — Core DAP Proxy Worker

**Primary purpose:** Orchestrates the full lifecycle of a single DAP (Debug Adapter Protocol) debug session inside a worker process. Spawns or connects to a language-specific debug adapter, manages the DAP handshake (initialize → launch/attach → configurationDone), forwards DAP requests/responses/events between parent and adapter, and handles graceful shutdown. Uses the **Adapter Policy** pattern (`AdapterPolicy` from `@debugmcp/shared`) to eliminate per-language hardcoding.

---

### Key Types

#### `DapProxyWorkerHooks` (L44–56)
Optional injection points for testing:
- `exit?: (code: number) => void` — override `process.exit` for unit tests
- `createTraceFile?: (sessionId, logDir) => string | undefined` — override DAP trace file creation

---

### `DapProxyWorker` Class (L58–1075)

**State fields:**
| Field | Type | Purpose |
|---|---|---|
| `state` | `ProxyState` | Lifecycle FSM: UNINITIALIZED → INITIALIZING → CONNECTED → SHUTTING_DOWN → TERMINATED |
| `adapterPolicy` | `AdapterPolicy` | Selected per-language policy (default: `DefaultAdapterPolicy`) |
| `adapterState` | `AdapterSpecificState` | Mutable policy-specific state updated during command/event lifecycle |
| `commandQueue` | `(DapCommandPayload \| SilentDapCommandPayload)[]` | Holds commands while adapter not yet initialized (js-debug pattern) |
| `preConnectQueue` | `DapCommandPayload[]` | Holds commands arriving before TCP connection is established |
| `isAttachMode` | `boolean` | Determines DAP sequencing and shutdown behavior |
| `deferInitializedHandling` | `boolean` | Gate to delay initialized event processing until after launch/attach |
| `initializedEventPromise` / `initializedEventResolver` | `Promise<void> / fn` | Synchronizes the "initialized" event across async flows |

---

### Constructor (L84–103)
- Creates a `CallbackRequestTracker` with a timeout callback.
- Initializes `adapterState` from `DefaultAdapterPolicy.createInitialState()`.
- Sets `exitHook` (default: `process.exit`) and `traceFileFactory` (default: writes `DAP_TRACE_FILE` env var to `logDir/dap-trace-<sessionId>.ndjson`).

---

### Public Methods

#### `getState()` (L152–154)
Returns current `ProxyState`. Intended for testing.

#### `handleCommand(command: ParentCommand)` (L159–195)
Top-level command dispatcher. Routes `init` → `handleInitCommand`, `dap` → `handleDapCommand`, `terminate` → `handleTerminate`. Errors are caught and sent as `ErrorMessage` to parent via `sendError`.

#### `handleInitCommand(payload: ProxyInitPayload)` (L200–294)
- Idempotent for `INITIALIZING` state (sends `init_received` and returns).
- Validates via `validateProxyInitPayload`, selects adapter policy via `selectAdapterPolicy`.
- Creates logger, sets up `GenericAdapterManager` and `DapConnectionManager`.
- Handles `dryRunSpawn` mode (calls `handleDryRun`, exits 0).
- Calls `startAdapterAndConnect`. On failure: resets state, sends diagnostics error, calls `shutdown()`, then exits 1 via `exitHook` after 100ms delay.

#### `handleTerminate()` (L942–969)
- Idempotent for SHUTTING_DOWN/TERMINATED.
- Attach mode: sends DAP `disconnect` with `terminateDebuggee=false` before shutdown.
- Calls `shutdown()`, sends `terminated` status to parent.

#### `shutdown()` (L974–1030)
Full teardown sequence:
1. Clears request tracker.
2. Sends DAP `disconnect` (`terminateDebuggee=!isAttachMode`) via `connectionManager`.
3. Calls `dapClient.shutdown('worker shutdown')`.
4. Waits 500ms for adapter to complete detach/cleanup.
5. Kills adapter process (tree-kill for launch mode only; never tree-kills in attach mode per comment on issue #156).
6. Sets state to TERMINATED.

---

### Private Methods

#### `selectAdapterPolicy(language?, adapterCommand?)` (L108–147)
Policy selection priority:
1. `language` field → `getPolicyForLanguage()` (preferred)
2. No `adapterCommand` → `PythonAdapterPolicy` (legacy fallback for pre-monorepo sessions)
3. Command-shape matching via `policy.matchesAdapter()` for each supported language
4. `DefaultAdapterPolicy` as final fallback

#### `startAdapterAndConnect(payload)` (L347–553)
Main DAP handshake driver:
- Gets spawn config from `adapterPolicy.getAdapterSpawnConfig()`
- **Spawn mode:** starts adapter process, registers `error`/`exit` handlers, sends `adapter_exited` status
- **Connect mode:** connects directly to remote DAP server (no process monitoring)
- Calls `connectWithRetry`, then `setupDapEventHandlers`
- Handles four initialization flows:
  - **Command-queuing adapters** (js-debug): skips handshake, drains pre-connect queue
  - **Attach-first mode** (`sendAttachBeforeInitialized`): sends attach immediately, races against initialized event (15s timeout) + attach failure
  - **Standard attach mode**: waits for initialized (5s timeout), then sends attach
  - **sendLaunchBeforeConfig** (Go/Java): two-phase — brief 2s wait before launch, then optional 10s wait after
  - **Standard launch mode** (Python): sends launch, waits for initialized via event handler

#### `setupDapEventHandlers()` (L559–650)
Wires DAP events from `connectionManager` to parent IPC:
- `onInitialized`: updates adapter state; for command-queuing adapters forwards event and drains queue; otherwise defers or calls `handleInitializedEvent`
- `onStopped`: auto-discovers threadId via `threads` request if missing; pre-fetches threads for Java (`adapterPolicy.name === 'java'`)
- `onTerminated`: forwards event, calls `shutdown()`
- `onClose`: sends `dap_connection_closed`, calls `shutdown()`

#### `handleInitializedEvent()` (L655–705)
Idempotent (guarded by `initializedEventHandled`). Groups initial breakpoints by resolved file path, calls `setBreakpoints` for each group, calls `sendConfigurationDone`, sets state to CONNECTED, sends `adapter_configured_and_launched`.

#### `handleDapCommand(payload)` (L710–820)
- Pre-connect queue if `INITIALIZING` and no `dapClient`.
- Consults `adapterPolicy.shouldQueueCommand()` — if queued, optionally injects a silent `configurationDone` before the payload, then drains queue.
- Otherwise: tracks request, optionally adds `runtimeExecutable` to launch args, sends via `dapClient.sendRequest`, updates adapter state, completes tracking, sends response.
- After launch/attach: triggers `ensureInitialStop()` for adapters requiring it.

#### `drainCommandQueue()` (L825–882)
- Optionally reorders via `adapterPolicy.processQueuedCommands`.
- For each command: skips response for `__silent` commands; otherwise tracks, sends, and forwards response to parent.

#### `drainPreConnectQueue()` (L916–924)
Replays queued pre-connect commands through `handleDapCommand`.

#### `ensureInitialStop(timeoutMs=12000)` (L887–911)
Polls `threads` every 100ms up to `timeoutMs`, sends `pause` to first valid thread. Used for JavaScript debugging initial stop.

#### `handleRequestTimeout(requestId, command, timeoutMs)` (L929–937)
Callback from `CallbackRequestTracker`; sends failure DAP response with timeout message.

---

### Message Helpers (L1033–1075)
All send via `this.dependencies.messageSender.send(message)`:
- `sendStatus(status, extra)` → `StatusMessage` (`type: 'status'`)
- `sendDapResponse(requestId, success, response?, error?)` → `DapResponseMessage` (`type: 'dapResponse'`)
- `sendDapEvent(event, body)` → `DapEventMessage` (`type: 'dapEvent'`)
- `sendError(message)` → `ErrorMessage` (`type: 'error'`)

---

### Key Architectural Decisions
- **Adapter Policy pattern**: All language-specific behavior (spawn config, DAP adapter type, command queuing, initialization sequence, state tracking) is delegated to `AdapterPolicy` objects from `@debugmcp/shared`.
- **Dual queue system**: `preConnectQueue` (TCP not yet open) vs `commandQueue` (TCP open but adapter not initialized, e.g. js-debug).
- **Silent commands**: `SilentDapCommandPayload` with `__silent: true` allows injecting internal DAP commands (e.g. `configurationDone`) without routing responses back to parent.
- **Attach mode isolation**: `isAttachMode` gates both the DAP sequence and shutdown behavior to prevent accidentally terminating the debuggee.
- **Process tree kill**: Only used in launch mode (`killProcessTree: !isAttachMode`), explicitly not used in attach mode.
- **IPC flush delay**: Uses `setImmediate` + 100ms `setTimeout` before exit to ensure IPC messages are delivered (critical on Windows).

---

### Dependencies (via `DapProxyDependencies`)
- `fileSystem.ensureDir` — creates log directory
- `loggerFactory` — creates session logger
- `processSpawner` — spawns adapter process (via `GenericAdapterManager`)
- `dapClientFactory` — creates DAP TCP client (via `DapConnectionManager`)
- `messageSender.send` — sends messages to parent process

---

### Notable Invariants
- `state` transitions are guarded; `handleInitCommand` throws on invalid state transitions.
- `handleInitializedEvent` is idempotent via `initializedEventHandled` flag.
- `shutdown` is idempotent (guards SHUTTING_DOWN/TERMINATED).
- `handleTerminate` is idempotent for SHUTTING_DOWN/TERMINATED.
- Attach mode: `dapClient` is set to `null` after auto-detach in `handleTerminate` (L964), so `shutdown()` skips the disconnect step.
