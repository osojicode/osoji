# tests\proxy\dap-proxy-worker.test.ts
@source-hash: b96c3f0e7264255c
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:41Z

## Purpose
Comprehensive unit tests for `DapProxyWorker`, covering state management, adapter policy selection, dry run mode, DAP command handling, timeout tracking, shutdown flows, attach/launch mode sequences, and command queueing for all supported language adapters.

## Test Structure

### Top-Level Suite: `DapProxyWorker` (L92–2065)

**Global setup (L105–140):**
- `beforeEach`: Creates fresh mocks for logger, DAP client, message sender, and dependencies; constructs `DapProxyWorker` with injected `workerExitSpy` to prevent real `process.exit` calls.
- `afterEach`: Clears timers, restores real timers, terminates worker if not already `TERMINATED`.

### Mock Factory Functions (L34–90)
| Factory | Returns | Key behavior |
|---|---|---|
| `createMockLogger` (L34) | `ILogger` | All methods are `vi.fn()` |
| `createMockFileSystem` (L41) | `IFileSystem` | `ensureDir` resolves, `pathExists` resolves true |
| `createMockProcessSpawner` (L46) | `IProcessSpawner` | `spawn` returns stub with pid 12345 |
| `createMockDapClient` (L56) | `IDapClient & EventEmitter` | Real EventEmitter with vi.fn-wrapped `sendRequest/connect/disconnect/shutdown`; `on/off/once/removeAllListeners` proxy to real emitter while being spy-able |
| `createMockMessageSender` (L88) | `{send: Mock}` | Tracks all outbound messages |

### Sub-Suites

**State Management (L142–180):**
- Verifies initial state is `UNINITIALIZED`.
- Dry run with `adapterCommand` → state becomes `TERMINATED`, exit hook called with code 1 after 150ms timer advance.

**Policy Selection (L182–340):**
Tests `worker.selectAdapterPolicy(language?, adapterCommand?)` via `(worker as any).selectAdapterPolicy(...)`:
- `js-debug` adapter command → `JsDebugAdapterPolicy` (name: `'js-debug'`)
- `debugpy` adapter → `PythonAdapterPolicy` (name: `'python'`)
- `dlv` command → `GoAdapterPolicy` (name: `'go'`)
- `rdbg` command → `RubyAdapterPolicy` (name: `'ruby'`)
- `JdiDapServer` in args → `JavaAdapterPolicy` (name: `'java'`)
- `codelldb` command → Rust policy (name: `'rust'`)
- `netcoredbg-bridge.js` or `netcoredbg` command → Dotnet policy (name: `'dotnet'`)
- `mock-adapter-process.js` → Mock policy (name: `'mock'`)
- Language string takes priority over command sniffing; unknown language falls back to command sniffing.

**Dry Run Mode (L342–393):**
- Successful dry run sends `{type:'status', status:'dry_run_complete', command: 'python -m debugpy.adapter --port 5678'}`.
- `DefaultAdapterPolicy` without adapterCommand throws `Cannot determine adapter command`.

**Hook Integration (L396–481):**
- Custom `createTraceFile` hook invoked with `(sessionId, logDir)` and sets `DAP_TRACE_FILE` env var.
- `fileSystem.ensureDir` rejection → exit hook called with 1 after 200ms; state stays `UNINITIALIZED`.
- Successful dry run: exit hook NOT called (Windows IPC timer cleared manually).

**Adapter Workflow Internals (L483–1041):**
- `startAdapterAndConnect` for JS (queueing policy): spawns process, connects, sends `adapter_connected`, state → `CONNECTED`.
- For Python (non-queue): spawns, connects, `initializeSession`, fires `initialized`, `sendLaunchRequest`, `setBreakpoints`, `sendConfigurationDone`, sends `adapter_configured_and_launched`, state → `CONNECTED`.
- Ruby attach (direct connect, no spawn): connects to attach port from `launchConfig`, calls `sendAttachRequest`.
- Go/Delve (`sendLaunchBeforeConfig: true`): verifies call order `initializeSession → sendLaunchRequest → sendConfigurationDone`.
- `ensureInitialStop`: polls `threads`, pauses first thread; logs warning when no threads within timeout.
- Process event wiring: adapter `error` → error message sent; `exit` → `adapter_exited` status; `stopped` event → `dapEvent` message; `terminated` event → `dapEvent` + calls `shutdown`.
- `handleTerminate` (launch mode): calls `disconnect(client, true)` BEFORE `shutdown('worker shutdown')` (issue #156 ordering).
- `handleTerminate` (attach mode): calls `disconnect(client, false)`.
- `processManager.shutdown` called with `{killProcessTree: true}` in launch mode, `{killProcessTree: false}` in attach mode.

**DAP Command Handling (L1044–1213):**
- Rejects DAP commands when not connected → `{type:'dapResponse', success:false, error:'DAP client not connected'}`.
- Rejects when in `TERMINATED` state.
- `sendRequest` rejection surfaces as `{success:false, error:'boom'}`.
- `timeoutMs` forwarded to `requestTracker.track(requestId, command, timeoutMs)` and `sendRequest(cmd, args, timeoutMs)` (issue #142).
- Without `timeoutMs`: `sendRequest` called with only 2 args.

**JS Adapter Queueing (L1216–1262):** Verifies JS policy selected; command either queued or rejected (implementation-dependent).

**Command Queue Draining (L1264–1355):**
- Queue with `shouldDefer:true` → injects `configurationDone` before queued command; both `sendRequest` calls verified.
- `timeoutMs` preserved on queued commands (issue #142).

**Pre-connect Queue (L1358–1383):** `drainPreConnectQueue` processes `preConnectQueue` array, calls `handleDapCommand` for each, empties queue.

**Timeout Handling (L1385–1412):** `requestTracker.track(id, cmd, 2000)` → after 2001ms fires error log and `{type:'dapResponse', success:false, error:"Request 'threads' timed out after 2s"}`.

**Error Handling (L1415–1567):**
- `ensureDir` failure → exit hook called with 1.
- `GenericAdapterManager.prototype.spawn` rejection → critical error logged, exit with 1.
- `DapConnectionManager.prototype.connectWithRetry` rejection → critical error logged, exit with 1.
- DAP `sendRequest` rejection → rejects mock (basic verification).

**Message Sending (L1570–1626):** Dry run sends `{type:'status', sessionId:'test-session'}`; second init on active worker sends `{type:'error', message:...Invalid state for init...}`.

**Shutdown (L1629–1661):** Clean shutdown → `TERMINATED` + `{type:'status', status:'terminated'}`; multiple `handleTerminate` calls emit `terminated` only once; `shutdown()` when already `SHUTTING_DOWN` logs warning and returns.

**Attach Mode Flow (L1664–1923):**
- Java attach: `initialized` event triggers attach request; `handleInitializedEvent` sets breakpoints and configDone.
- Python attach (issue #145): sends attach first, `initialized` arrives after attach, `configurationDone` resolves the deferred attach response; verifies `callOrder === ['attach', 'configurationDone']`.
- Python attach fail-fast: `sendAttachRequest` rejection propagates quickly (< 5s, not 15s timeout).

**Go/Java Launch Sequence (L1926–2046):** Both verify "Phase 1: Waiting briefly for 'initialized' event before launch" log message and `sendLaunchRequest` called.

**handleCommand terminate (L2049–2065):** `{cmd:'terminate'}` routes to `handleTerminate`, state → `TERMINATED`.

## Key Architectural Patterns Tested
- **Adapter Policy Pattern**: `selectAdapterPolicy(language?, adapterCommand?)` drives all per-language behavior divergence.
- **Dependency Injection**: `DapProxyWorker(dependencies, hooks)` — all I/O, logging, process spawning, and DAP client creation injected.
- **Exit Hook Injection**: `{exit: fn}` hook prevents `process.exit` in tests (issue #183).
- **State Machine**: `ProxyState.UNINITIALIZED → INITIALIZING → CONNECTED → SHUTTING_DOWN → TERMINATED`.
- **Pre-connect Queue**: `preConnectQueue` accumulates DAP commands before connection; drained after connect.
- **Request Tracker**: Internal `requestTracker` enforces per-request timeout and emits failure messages.
- **Windows IPC Fix**: Dry run schedules exit via `setImmediate + setTimeout(100ms)`, requiring timer advancement in tests.

## Important Invariants
- `disconnect` must be called BEFORE `dapClient.shutdown` to avoid orphaned debuggee processes (issue #156).
- `timeoutMs` must be forwarded from payload through queue to `sendRequest` (issue #142).
- Python attach: `sendAttachRequest` must not block on response before `configurationDone` (issue #145).
- Go/Delve: `sendLaunchRequest` must precede `configurationDone` in call order.
