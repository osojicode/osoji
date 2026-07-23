# tests\unit\proxy\proxy-manager.branch-coverage.test.ts
@source-hash: 832af11d970ac1fc
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:06Z

## Branch Coverage Tests for `ProxyManager`

Unit test file targeting branch-level coverage of `ProxyManager` (from `src/proxy/proxy-manager.ts`) via white-box testing. Tests directly access private members using `(manager as unknown as {...})` casts.

### Test Infrastructure

**`StubProxyProcess` (L16–30)**: Extends `EventEmitter`, implements `IProxyProcess`. Key fields:
- `pid = 9999`, `sessionId = 'session-1'`
- `stdin`/`stdout` are null; `stderr` is a bare `EventEmitter` cast to `ReadableStream`
- All methods are `vi.fn()` mocks: `send`, `sendCommand`, `kill`, `waitForInitialization`

**`beforeEach` setup (L39–61)**: Constructs `ProxyManager(null, launcher, fileSystem, logger)` then directly injects internal state:
- `sessionId = 'session-1'`
- `proxyProcess = new StubProxyProcess()`
- `isInitialized = true`
- `dapState = createInitialState('session-1')`

### Test Scenarios

| Test | Private method tested | Key assertion |
|------|----------------------|---------------|
| L67–80 | `handleProxyMessage` | `killProcess` command from `dapCore.handleProxyMessage` triggers `proxyProcess.kill()` |
| L82–96 | `handleProxyMessage` | `sendToProxy` command routes to private `sendCommand` |
| L98–108 | `handleProxyMessage` | Null `dapState` → `logger.error('[ProxyManager] DAP state not initialized')` |
| L110–118 | `handleStatusMessage` | `proxy_minimal_ran_ipc_test` status → `proxyProcess.kill()` |
| L120–133 | `handleStatusMessage` | `adapter_connected` status → sets `isInitialized = true`, emits `'initialized'` event |
| L135–149 | `handleStatusMessage` | `dry_run_complete` with blank `command`/`script` does NOT overwrite existing `dryRunCommandSnapshot`/`dryRunScriptPath` |
| L151–169 | `handleDapEvent` | `stopped` event with empty body → emits `(undefined, 'unknown')`, `currentThreadId` stays null |
| L171–201 | `handleDapEvent` | `stopped` event with `{threadId: 42, reason: 'breakpoint'}` → sets `currentThreadId`, calls `barrier.onDapEvent` |
| L203–224 | `handleDapEvent` | `continued` event → emits `'continued'`; other events → emits `'dap-event'` |
| L226–279 | `sendDapRequest` | `awaitResponse` barrier: request sent, response resolves promise, `barrier.dispose()` called, `activeLaunchBarrier` nulled |
| L281–313 | `sendDapRequest` | Transport error → `barrier.dispose()` called, `activeLaunchBarrier` nulled, error re-thrown |
| L315–345 | `clearActiveLaunchBarrier` | Mismatched barrier reference → early return, active barrier unchanged, `dispose` not called |
| L347–366 | `clearActiveLaunchBarrier` | `dispose()` throws → warning logged, `activeLaunchBarrier` still set to null |

### Key Architectural Observations

- **Functional core integration**: `dapCore.handleProxyMessage` (from `src/dap-core/index.ts`) is the pure functional state reducer. The `ProxyManager` executes side-effect commands (`killProcess`, `sendToProxy`) returned from it (L68–80, L82–96).
- **AdapterLaunchBarrier lifecycle**: `activeLaunchBarrier` is set before sending a DAP request and cleared (via `clearActiveLaunchBarrier`) either on response receipt or error. Barrier with `awaitResponse: true` gets `onRequestSent` called with the requestId and `dispose` called on cleanup.
- **`dapState` null-guard branch**: Explicitly tested at L98–108 — any message processed when `dapState` is null logs an error instead of crashing.
- **`dry_run_complete` guard**: Existing snapshot values are preserved if incoming `command`/`script` fields are blank/whitespace (L135–149).
- **`stopped` event**: `currentThreadId` is updated only when `body.threadId` is defined; `reason` defaults to `'unknown'` when absent (L151–169).

### Dependencies
- `ProxyManager` from `src/proxy/proxy-manager.ts` (class under test)
- `createInitialState`, `handleProxyMessage` from `src/dap-core/index.ts` (functional core)
- `@debugmcp/shared`: `DebugLanguage`, `IDebugAdapter`, `IFileSystem`, `ILogger`, `IProxyProcess`, `IProxyProcessLauncher`, `AdapterLaunchBarrier`
