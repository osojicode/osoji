# tests\unit\proxy\proxy-manager-message-handling.test.ts
@source-hash: ad2c161d10b406d0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:15Z

## Purpose
Unit test suite for `ProxyManager` message handling, cleanup, and lifecycle behavior. Uses `TestProxyManager` (a test double) for most tests and the real `ProxyManager` for regression/edge-case tests that require direct internal access via type-casting.

## File Structure
Single `describe('ProxyManager Message Handling')` block (L20–L1139) with nested describes:
- **message handling** (L58–L294): Tests for various message types dispatched via `simulateMessage`/`simulateStoppedEvent`/`simulateContinuedEvent`
- **proxy process exit handling** (L296–L355): Exit with clean code, error code, signal, and error events
- **cleanup scenarios** (L357–L408): Pending request cleanup, concurrent requests, double-stop
- **stop() drains in-flight DAP requests (issue #122 regression)** (L410–L509): Regression tests for drain behavior during stop(); uses real `ProxyManager` with `fakeProcess`
- **DAP request handling edge cases** (L511–L564): Not-running proxy, concurrent same-command requests, failed responses
- **state management during message handling** (L566–L594): Thread ID tracking, dry-run mode
- **resilience scenarios** (L596–L1031): Invalid messages, timeouts, per-request timeout overrides, IPC payload inspection, bootstrap missing, transport errors, adapter validation, js-debug fire-and-forget launch, launch barrier lifecycle
- **status and lifecycle handling** (L1034–L1113): `adapter_connected` → `initialized` event, `adapter_exited` → `exit` event, pending request rejection on proxy exit
- **IPC smoke test status** (L1116–L1139): `proxy_minimal_ran_ipc_test` kills process

## Key Test Patterns

### TestProxyManager (primary test double, L20–L408)
- Instantiated via `new TestProxyManager(mockLogger)` + `await proxyManager.start(mockConfig)` in `beforeEach` (L44–48)
- `simulateMessage(msg)` — injects arbitrary message objects into handler
- `simulateStoppedEvent(threadId, reason)` — injects DAP stopped event
- `simulateContinuedEvent()` — injects DAP continued event
- `setMockResponse(command, response)` — configures immediate mock response for `sendDapRequest`
- `getCurrentThreadId()` — exposes internal thread ID state

### Real ProxyManager tests (L418–L1139)
Use internal access pattern: `(proxyManager as any).fieldName = value` to bypass encapsulation. Key internal fields accessed:
- `proxyProcess` — injected fake `EventEmitter`-based process mock with `sendCommand`, `send`, `killed`, `exitCode`, `kill`
- `isInitialized` — set to `true` to bypass initialization guard
- `sessionId` — set directly for message routing
- `dapState` — set via `createInitialState(sessionId)`
- `stopDrainTimeoutMs` — overridden to `50` in drain timeout regression test (L501)
- `pendingDapRequests` — `Map<string, {resolve, reject}>` inspected/mutated directly
- `handleProxyMessage(msg)` — called directly to inject messages
- `handleStatusMessage(msg)` — called directly for status tests
- `handleProxyExit(code, signal)` — called directly
- `prepareSpawnContext(config)` — called directly for spawn validation tests
- `setupEventHandlers()` — called directly to wire event handlers on fakeProcess

## Critical Test: Drain Window Regression (issue #122) (L410–L508)
`makeStoppableProxyManager()` (L418–L453) builds a real `ProxyManager` with a fake process whose `send()` triggers `exit` via `setImmediate`. Tests:
1. **Resolves in-flight request inside drain window** (L455–L496): `continuePromise` + concurrent `stop()`, response injected via `setImmediate` → must resolve successfully (not cancel)
2. **Cancels requests after bounded drain timeout** (L498–L508): `stopDrainTimeoutMs=50`, hung request → rejects with `/cancelled during proxy shutdown/i`

## Key Message Types Tested
| `type` | `status`/`event` | Expected behavior |
|--------|-----------------|-------------------|
| `status` | `adapter_configured_and_launched` | emits `adapter-configured` |
| `status` | `dry_run_complete` | emits `dry-run-complete` with command+script |
| `status` | `adapter_connected` | emits `initialized` |
| `status` | `adapter_exited` | emits `exit` with code+signal |
| `status` | `proxy_minimal_ran_ipc_test` | calls `kill()` on proxy process |
| `dapEvent` | `stopped` | emits `stopped`, updates `currentThreadId` |
| `dapEvent` | `continued` | emits `continued`, clears `currentThreadId` |
| `dapEvent` | `terminated` | emits `terminated` |
| `dapEvent` | `exited` | emits `exited` |
| `dapResponse` | — | resolves pending request promise |
| `error` | — | emits `error` |

## Mock Config (L30–L42)
```ts
{ sessionId: 'test-session', language: DebugLanguage.PYTHON, executablePath: '/usr/bin/python3',
  adapterHost: 'localhost', adapterPort: 5678, logDir: '/tmp/logs',
  scriptPath: '/path/to/script.py', scriptArgs: ['arg1'], initialBreakpoints: [],
  dryRunSpawn: false, stopOnEntry: true }
```

## Timeout Behavior Tests (L664–L717)
- Default timeout: 35,000 ms
- Per-request `timeoutMs` override: fires at `timeoutMs + 5000` (parent margin)
- IPC payload includes `timeoutMs` only when override is set; key must be absent (not undefined) to prevent JSON leakage

## Dependencies
- `TestProxyManager` from `../test-utils/test-proxy-manager.js` — primary test double
- `ProxyManager` from `../../../src/proxy/proxy-manager.js` — real implementation under test
- `ProxyConfig` from `../../../src/proxy/proxy-config.js` — config type
- `createInitialState` from `../../../src/dap-core/index.js` — DAP state factory
- `createMockLogger`, `createMockFileSystem` from `../test-utils/mock-factories.js`
- `DebugLanguage`, `IDebugAdapter`, `IProxyProcess` from `@debugmcp/shared`
- `vitest` for test runner + fake timers; `EventEmitter` for fake process