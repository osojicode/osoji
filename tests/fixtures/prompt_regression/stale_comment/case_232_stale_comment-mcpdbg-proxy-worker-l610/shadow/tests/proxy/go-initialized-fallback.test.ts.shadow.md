# tests\proxy\go-initialized-fallback.test.ts
@source-hash: 2da73bfa8fdcae7d
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:34Z

## Regression Tests: Go/Delve Two-Phase `initialized` Event Handling

Tests the `sendLaunchBeforeConfig` / two-phase `initialized` event fallback code path in `DapProxyWorker`. Specifically validates that when Delve (Go debugger) sends its `initialized` DAP event _after_ the `launch` request (rather than before), the proxy correctly recovers via a Phase 2 fallback mechanism.

### Purpose & Scope
Covers three scenarios in the `startAdapterAndConnect` internal method of `DapProxyWorker`:
1. **Phase 2 fallback (L141-224)**: `initialized` arrives after `launch` — proxy uses fallback, warns, and completes successfully.
2. **Phase 1 happy path (L230-295)**: `initialized` arrives promptly after `initialize` — no fallback needed.
3. **Full timeout (L301-348)**: `initialized` never arrives — Phase 2 10s timeout triggers, rejects with specific error.
4. **Timeout boundary regression (L357-418)**: `initialized` arrives at 3s — proves Phase 1 timeout is 2s (not 5s), forces Phase 2 path.

### Key Mock Infrastructure

- **`createMockLogger` (L26-31)**: Returns `ILogger` with all methods as `vi.fn()`.
- **`createMockFileSystem` (L33-36)**: Returns `IFileSystem`; `pathExists` resolves `true`, `ensureDir` resolves `undefined`.
- **`createMockProcessSpawner` (L38-46)**: Returns `IProcessSpawner`; `spawn` returns a minimal process stub.
- **`createMockDapClient` (L48-77)**: Creates an `EventEmitter` augmented with DAP methods (`sendRequest`, `connect`, `disconnect`, `shutdown`). Wraps `on`/`off`/`once`/`removeAllListeners` with `vi.fn()` while still forwarding to real EventEmitter — critical so that test-driven `.emit()` calls actually reach registered handlers.
- **`createMockMessageSender` (L79-81)**: Returns `{ send: vi.fn() }`.

### Test Fixture — `GO_PAYLOAD` (L83-98)
A `ProxyInitPayload` for a Delve session (`cmd: 'init'`, `executablePath: 'dlv'`, `adapterCommand.command: 'dlv'`).

### Test Architecture Pattern
All tests in `beforeEach` (L109-123):
- Construct `DapProxyDependencies` with the mock factories.
- Instantiate `DapProxyWorker` with a `{ exit: vi.fn() }` process mock.

Each test manually injects internal private state via `(worker as any)`:
- `logger`, `processManager`, `connectionManager`, `adapterPolicy`, `adapterState`, `currentInitPayload`, `state`
- Uses `GoAdapterPolicy` from `@debugmcp/shared` and `GoAdapterPolicy.createInitialState()`.
- Calls `(worker as any).startAdapterAndConnect(GO_PAYLOAD)` directly.

`afterEach` (L125-135): Clears timers, restores real timers, calls `worker.handleTerminate()` if not already `TERMINATED`.

### Connection Stub Pattern
Per-test `connectionStub` objects implement the `connectionManager` interface:
- `connectWithRetry`: resolves to `mockDapClient`
- `setupEventHandlers`: manually wires `initialized`/`output`/`stopped`/`terminated` events to `mockDapClient` EventEmitter — allows `mockDapClient.emit('initialized')` to trigger the proxy's handler
- `initializeSession`, `sendLaunchRequest`, `setBreakpoints`, `sendConfigurationDone`: push to `callOrder[]` and optionally emit `initialized`

### Critical Timing Contracts Verified
- Phase 1 timeout = **2 seconds** (tested in L357-418 via `vi.advanceTimersByTimeAsync(2100)`)
- Phase 2 timeout = **10 seconds** (tested in L301-348 via `vi.advanceTimersByTimeAsync(13000)`)
- Phase 2 fallback warning message: `'not received within 2s'`
- Phase 2 start log: `'Phase 2: Waiting for "initialized" event after launch'`
- Phase 2 success log: `'fallback succeeded'`
- Phase 1 success log: `'"initialized" event received before launch'`
- Phase 2 timeout error: `/Timeout waiting for initialized event \(after launch fallback\)/`

### DAP Sequence Assertions
All passing tests verify call ordering: `initializeSession` → `sendLaunchRequest` → `sendConfigurationDone`.
Fallback test additionally verifies `messageSender.send` was called with `{ type: 'status', status: 'adapter_configured_and_launched' }` (L218-222), and final `worker.getState() === ProxyState.CONNECTED`.

### Dependencies
- `DapProxyWorker` from `../../src/proxy/dap-proxy-worker.js`
- `DapProxyDependencies`, `ILogger`, `IFileSystem`, `IProcessSpawner`, `IDapClient`, `ProxyInitPayload`, `ProxyState` from `../../src/proxy/dap-proxy-interfaces.js`
- `GoAdapterPolicy` from `@debugmcp/shared`
- Vitest (`describe`, `it`, `expect`, `beforeEach`, `afterEach`, `vi`)
