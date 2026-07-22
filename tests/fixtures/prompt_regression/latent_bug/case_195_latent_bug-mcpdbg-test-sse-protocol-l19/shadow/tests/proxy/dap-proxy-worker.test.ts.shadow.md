# tests\proxy\dap-proxy-worker.test.ts
@source-hash: b96c3f0e7264255c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:42Z

## Purpose
Comprehensive unit test suite for `DapProxyWorker`, covering the Adapter Policy pattern, state machine transitions, DAP command handling, dry run mode, adapter workflow internals, timeout/error handling, and multi-language adapter policy selection.

## Test Structure Overview

### Top-level describe: `DapProxyWorker` (L92-2066)
All tests share a `beforeEach` (L105-122) that creates fresh mock dependencies and a `DapProxyWorker` with an injected `workerExitSpy` (preventing real `process.exit` calls). `afterEach` (L124-140) cleans up timers and terminates the worker if not already terminated.

## Mock Factories

| Factory | Lines | Purpose |
|---|---|---|
| `createMockLogger` | L34-39 | `ILogger` with `vi.fn()` for info/error/debug/warn |
| `createMockFileSystem` | L41-44 | `IFileSystem` with `ensureDir` → resolves undefined, `pathExists` → resolves true |
| `createMockProcessSpawner` | L46-54 | `IProcessSpawner` returning stub ChildProcess with pid 12345 |
| `createMockDapClient` | L56-86 | `IDapClient & EventEmitter` — wraps real EventEmitter so events propagate; spies on `on/off/once/removeAllListeners`; mocks `sendRequest/connect/disconnect/shutdown` |
| `createMockMessageSender` | L88-90 | `{ send: vi.fn() }` |

### Key dependency wiring (L110-122)
- `loggerFactory`: async vi.fn resolving to `mockLogger`
- `dapClientFactory.create`: async vi.fn resolving to `mockDapClient`
- `messageSender`: `mockMessageSender`
- Worker constructed as `new DapProxyWorker(dependencies, { exit: workerExitSpy })`

## Test Suites

### State Management (L142-180)
- Verifies initial `ProxyState.UNINITIALIZED` (L143-145)
- Dry-run init transitions to `TERMINATED`, exit hook called with code 1 after 150ms fake-timer advance (L147-179)

### Policy Selection (L182-340)
Tests `worker.selectAdapterPolicy(language?, adapterCommand?)` — called as private method via `(worker as any)`:
- Python (no adapter cmd, `.py` script), js-debug (vsDebugServer.js), debugpy (python -m debugpy.adapter)
- Go (dlv), Ruby (rdbg), Java (JdiDapServer), Rust (codelldb), Dotnet (netcoredbg), Mock (mock-adapter-process.js)
- Language hint overrides command sniffing (L319-325); unknown language falls back to command sniffing (L333-339)

### Dry Run Mode (L342-393)
- Reports `dry_run_complete` status with formatted command string (L343-372)
- Throws `Cannot determine adapter command` when `DefaultAdapterPolicy` cannot provide spawn config (L374-393)

### Hook Integration (L396-481)
- `createTraceFile` hook invoked with sessionId+logDir; sets `DAP_TRACE_FILE` env (L412-435)
- Exit hook called with code 1 after `ensureDir` failure (437-461); needs 200ms fake-timer advance past setImmediate+setTimeout(100ms) IPC flush
- Exit hook NOT called during successful dry run (L463-480)

### Adapter Workflow Internals (L483-1041)
All tests inject private fields via `(worker as any)` — bypasses initialization and tests individual methods directly.

**startAdapterAndConnect** scenarios:
- JS (queueing policy): spawns, connects, emits `adapter_connected` → `CONNECTED` (L505-556)
- Python (non-queue policy): spawns, connects, initializeSession, waits for `initialized` event via `setImmediate`, sends launch → `adapter_configured_and_launched` (L558-630)
- Ruby attach (direct-connect): no spawn, connects to launchConfig port, calls `sendAttachRequest` (L632-687)
- Go (sendLaunchBeforeConfig=true): verifies `initializeSession → sendLaunchRequest → sendConfigurationDone` ordering using `callOrder` array (L689-789)

**ensureInitialStop** (L791-845):
- With threads: calls `threads` then `pause` with correct threadId (L791-811)
- Without threads: logs warning, uses fake timers with 120ms timeout (L813-845)

**Event wiring** (L847-958): adapter process `error`/`exit` events propagate as messages; `onStopped`/`onTerminated` handlers relay dapEvents and trigger shutdown

**handleTerminate** (L960-1041):
- Launch mode: `disconnect(client, true)` called BEFORE `shutdown('worker shutdown')` — ordering enforced (L960-980, invocationCallOrder check at L976-978)
- Launch mode tree-kill: `processStub.shutdown` called with `{ killProcessTree: true }` (L982-1002)
- Attach mode no tree-kill: `{ killProcessTree: false }` (L1004-1025)
- Attach mode auto-detach: `disconnect(client, false)` (L1027-1041)

### DAP Command Handling (L1044-1213)
- Rejects DAP commands before connection: sends `dapResponse { success: false, error: 'DAP client not connected' }` (L1044-1086)
- Rejects after termination (L1088-1127)
- Surfaces sendRequest rejections as error responses (L1129-1158)
- Forwards `timeoutMs` to requestTracker.track and sendRequest (L1161-1188, issue #142)
- Omits timeout arg when no `timeoutMs` (L1190-1213)

### JavaScript Adapter Command Queueing (L1216-1262)
- Verifies JS policy selected and at least one dapResponse produced for setBreakpoints (L1217-1261)

### Command Queue Draining (L1264-1355)
- `deferConfigDone=true` policy: queued launch triggers configurationDone injection, then sends launch; exactly 2 sendRequest calls (L1265-1315)
- `timeoutMs` retained on queued commands (L1317-1355, issue #142)

### Pre-connect Queue Handling (L1358-1383)
- `drainPreConnectQueue` calls `handleDapCommand` for each queued item, empties queue (L1359-1382)

### Timeout Handling (L1385-1412)
- `requestTracker.track(id, cmd, ms)` triggers timeout → error log + `dapResponse { success: false, error: "Request '...' timed out after 2s" }` (L1386-1412)

### Error Handling (L1415-1567)
- `ensureDir` failure → exit hook with code 1 after 200ms (L1416-1446)
- `GenericAdapterManager.prototype.spawn` rejection → exit hook 1 + critical error log (L1448-1493)
- `DapConnectionManager.prototype.connectWithRetry` rejection → exit hook 1 + critical error log (L1495-1540)
- DAP command error: verifies mock rejection propagation (L1542-1567)

### Message Sending (L1570-1626)
- Status message includes `sessionId` (L1571-1595)
- Repeated init → error message containing `Invalid state for init` (L1597-1626)

### Shutdown (L1629-1661)
- Clean shutdown → `TERMINATED`, sends `{ type: 'status', status: 'terminated' }` (L1630-1639)
- Idempotent: second call produces no second `terminated` message (L1641-1650)
- Early return when `SHUTTING_DOWN` (L1652-1661)

### Attach Mode Flow (L1664-1923)
- Java attach: waits for `initialized`, then `sendAttachRequest`, logs expected messages (L1665-1727, L1729-1793)
- Python attach ordering (issue #145): `attach → (initialized event) → configurationDone`; attach response deferred until configurationDone (L1800-1869)
- Python attach fail-fast: rejects ECONNREFUSED immediately, not after 15s timeout (L1871-1923)

### Go/Java Launch Sequence (L1926-2047)
- Go: two-phase initialized (Phase 1 log), `sendLaunchRequest` called (L1927-1984)
- Java: two-phase launch + `handleInitializedEvent`, logs `"initialized" event received before launch` (L1986-2046)

### handleCommand terminate (L2049-2065)
- Routes `{ cmd: 'terminate' }` to handleTerminate, reaches `TERMINATED` (L2050-2064)

## Critical Patterns
- **Windows IPC flush**: exit scheduling uses `setImmediate` + `setTimeout(100ms)`; tests advance 150-200ms with `vi.advanceTimersByTimeAsync` to trigger
- **Private field injection**: `(worker as any).field = stub` used throughout Adapter Workflow tests to bypass full initialization
- **invocationCallOrder**: Ordering of `disconnect` before `shutdown` enforced at L976-978
- **issue #142**: `timeoutMs` forwarding verified in two separate suites (direct commands L1161, queued commands L1317)
- **issue #145**: Python attach ordering (attach-before-initialized) tested at L1800
- **issue #156**: disconnect-before-shutdown ordering (L970-978)