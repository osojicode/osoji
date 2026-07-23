# tests\unit\proxy\proxy-manager-message-handling.test.ts
@source-hash: ad2c161d10b406d0
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:03Z

## Purpose
Unit test suite for `ProxyManager` message handling, event propagation, cleanup, and edge cases in proxy IPC communication. Uses `TestProxyManager` (a simplified test double) for most tests and direct `ProxyManager` instantiation for lower-level internals.

## Test Structure

### Top-level describe: `ProxyManager Message Handling` (L20–1139)
- **beforeEach** (L25–49): Creates `TestProxyManager` with mock logger and `ProxyConfig` (Python session), calls `proxyManager.start(mockConfig)`.
- **afterEach** (L51–56): Stops proxy if running, clears all mocks.

### Nested `describe` blocks:

#### `message handling` (L58–294)
Tests `simulateMessage()` / `simulateStoppedEvent()` / `simulateContinuedEvent()` on `TestProxyManager`:
- Status messages: `adapter_configured_and_launched` → emits `adapter-configured` (L59–75)
- `dry_run_complete` status → emits `dry-run-complete` with command+script args (L77–101)
- DAP `stopped` event → emits `stopped` with threadId (L103–116)
- `currentThreadId` update on stopped (L118–126)
- `currentThreadId` preservation when stopped body lacks threadId (L128–146)
- DAP `continued` event (L148–158)
- DAP `terminated` event (L160–175)
- DAP `exited` event (L177–199)
- DAP response messages via `setMockResponse` + `sendDapRequest` (L201–226)
- Error messages → emits `error` (L228–247)
- Invalid/malformed/empty/wrong-session messages → no throw, no spurious events (L249–293)

#### `proxy process exit handling` (L296–355)
- Clean proxy exit via `stop()` → emits `exit` (L297–307)
- Exit with error code → logger.info called (L309–322)
- Exit with signal → logger.info called (L324–337)
- Proxy error events (L339–354)

#### `cleanup scenarios` (L357–408)
- Pending requests cleanup on `stop()` (L358–368)
- Multiple concurrent requests (L371–386)
- `stop()` with no pending requests (L388–391)
- Timeout clearing during cleanup (L393–398)
- Double `stop()` idempotency (L400–407)

#### `stop() drains in-flight DAP requests (issue #122 regression)` (L410–509)
Key regression tests for the drain window behavior:
- **`makeStoppableProxyManager()`** (L418–453): Factory that creates a real `ProxyManager` with `fakeProcess` (EventEmitter + `sendCommand`/`send`/`kill` mocks). Directly injects `proxyProcess`, `isInitialized`, `sessionId`, `dapState` via type-casting.
- L455–496: In-flight `continue` response that arrives during drain window resolves successfully (not rejected).
- L498–508: Hung requests are cancelled after bounded drain timeout (`stopDrainTimeoutMs = 50`).

#### `DAP request handling edge cases` (L511–564)
- Request when proxy stopped → throws `'Proxy not running'` (L512–519)
- Concurrent same-command requests (L522–537)
- Normal request completion (L539–544)
- Failed DAP response (L546–563)

#### `state management during message handling` (L566–594)
- Thread ID update from stopped events (L567–569)
- Thread ID cleared on continued events (L571–580)
- Dry-run mode state changes (L582–593)

#### `resilience scenarios` (L596–1032)
Complex tests using real `ProxyManager` with partial internal state injection:
- **`makeInitializedProxyManager()`** (L643–662): Factory for initialized `ProxyManager` with mock `sendCommand`.
- Logs invalid proxy messages with `warn` (L601–611)
- DAP request timeout after 35s → rejects with `/Debug adapter did not respond/i`, clears `pendingDapRequests` (L614–641)
- Per-request `timeoutMs` override: 60s override + 5s margin = 65s (L664–679)
- Short `timeoutMs` override: 1s + 5s margin = 6s (L682–696)
- `timeoutMs` included in IPC payload when set, absent when not set (L698–717)
- Bootstrap worker script not found → throws `'Bootstrap worker script not found'` (L719–750)
- Transport errors on `sendCommand` propagate, `pendingDapRequests` cleared (L752–781)
- Adapter validation failure → throws `/Invalid environment/` (L783–816)
- `js-debug` fire-and-forget launch (L818–869): Uses `createLaunchBarrier` with `awaitResponse: false`.
- Early proxy exit clears adapter launch barrier → rejects with `/Proxy exited/`, calls `barrier.onProxyExit` + `barrier.dispose` (L871–920).
- Barrier disposed after DAP response when `awaitResponse: true` (L922–981)
- Barrier disposed on request timeout (L983–1031)

#### `status and lifecycle handling` (L1034–1114)
Direct calls to internal `handleStatusMessage` / `handleProxyExit`:
- `adapter_connected` → emits `initialized` (L1035–1058)
- `adapter_exited` → emits `exit` with code+signal (L1060–1085)
- `handleProxyExit` rejects pending requests, clears map (L1087–1113)

#### `IPC smoke test status` (L1116–1139)
- `proxy_minimal_ran_ipc_test` status → kills proxy process (L1117–1138)

## Key Patterns
- `TestProxyManager` wraps `ProxyManager` with synchronous start and helper simulation methods (`simulateMessage`, `simulateStoppedEvent`, `simulateContinuedEvent`, `setMockResponse`).
- Real `ProxyManager` tests use `as unknown as { field }` type-casting to inject internal state (`proxyProcess`, `isInitialized`, `sessionId`, `dapState`, `pendingDapRequests`).
- Private method calls (`handleStatusMessage`, `handleProxyExit`, `handleProxyMessage`, `prepareSpawnContext`, `setupEventHandlers`) accessed via type-cast for white-box testing.
- `vi.useFakeTimers()` used in timeout regression tests; cleanup via `vi.useRealTimers()` in `afterEach` or `finally`.
- Issue #122 regression: drain window ensures in-flight responses resolve before `stop()` rejects them.
- Issue #142 regression: per-request `timeoutMs` override respected (default 30s + 5s margin = 35s, custom 60s + 5s = 65s).

## Dependencies
- `TestProxyManager`: `../test-utils/test-proxy-manager.js`
- `ProxyManager`: `../../../src/proxy/proxy-manager.js`
- `ProxyConfig`: `../../../src/proxy/proxy-config.js`
- `createInitialState`: `../../../src/dap-core/index.js`
- `createMockLogger`, `createMockFileSystem`: `../test-utils/mock-factories.js`
- `DebugLanguage`, `IDebugAdapter`, `IProxyProcess`: `@debugmcp/shared`
