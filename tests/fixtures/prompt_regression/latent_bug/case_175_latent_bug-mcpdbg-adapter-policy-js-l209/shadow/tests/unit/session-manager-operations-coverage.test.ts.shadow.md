# tests\unit\session-manager-operations-coverage.test.ts
@source-hash: 79c6777d2213a5bf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:26Z

## Purpose
Targeted unit test suite for `SessionManagerOperations` covering error paths, edge cases, and behavioral contracts for the session management layer. Uses a concrete `TestableSessionManagerOperations` subclass to exercise the abstract base class.

## Architecture
- **File**: `tests/unit/session-manager-operations-coverage.test.ts`
- **Test Framework**: Vitest with fake timers for async timing tests
- **SUT**: `SessionManagerOperations` (abstract) via `TestableSessionManagerOperations` (L12-16)
- **Session fixture**: `mockSession` (L61-72) with `SessionState.CREATED` and `SessionLifecycleState.ACTIVE`
- **Dependency injection**: Full mock dependency tree (L94-123) injected via constructor

## Test Class Structure

### `TestableSessionManagerOperations` (L12-16)
Concrete subclass implementing the abstract `handleAutoContinue` as a no-op; allows direct instantiation.

### Mock Dependency Shape (L34-130)
- `mockLogger`: `{ info, error, warn, debug }` all `vi.fn()`
- `mockProxyManager` (L44-58): Fluent event emitter mock (`on/off/once/removeListener` all return `this`). Key methods: `isRunning`, `getCurrentThreadId`, `sendDapRequest`, `stop`, `start`
- `mockSession` (L61-72): Plain object with `id='test-session'`, `language='python'`, `state`, `sessionLifecycle`, `proxyManager`, `breakpoints: Map`, `executablePath`
- `mockSessionStore` (L75-91): `get`, `getOrThrow` (throws `SessionNotFoundError` for wrong ID), `update`, `updateState` (mutates `mockSession.state`), `delete`, `remove`, `getAll`
- `mockDependencies` (L94-123): `sessionStoreFactory`, `proxyManagerFactory`, `fileSystem`, `environment`, `networkManager`, `adapterRegistry`

## Test Groups and Key Behaviors

### `startProxyManager` edge cases (L136-273)
- **L137-143**: Log dir creation failure → throws `'Failed to create session log directory: disk full'`
- **L145-155**: Adapter `resolveExecutablePath` rejection for python → `PythonNotFoundError`
- **L157-163**: `pathExists` returns false after `ensureDir` → throws `/could not be created/`
- **L165-176**: Adapter rejection for non-python language → `DebugSessionCreationError`
- **L178-238**: Full happy-path: verifies `ensureDir`, `findFreePort`, `adapterRegistry.create`, `proxyInstance.start`, `mockSession.proxyManager` assignment, `sessionStore.update` with `logDir` containing `run-`
- **L240-273**: MSVC toolchain: adapter has `consumeLastToolchainValidation()` returning `{ compatible: false, behavior: 'warn', toolchain: 'msvc' }` → throws `Error('MSVC_TOOLCHAIN_DETECTED')` with `.toolchainValidation` property; `resolveExecutablePath` not called; `sessionStore.update` called with `toolchainValidation`

### `startDebugging` toolchain handling (L276-323)
- MSVC error from `startProxyManager` → `startDebugging` returns `{ success: false, error: 'MSVC_TOOLCHAIN_DETECTED', canContinue: true, data: { toolchainValidation, message } }`
- State resets to `SessionState.CREATED`; `sessionStore.update` called with `sessionLifecycle: SessionLifecycleState.CREATED`

### Operation failures (L325-407)
- **continue**: `ProxyNotRunningError` when `proxyManager=null` or `isRunning()=false`; DAP rejection propagates
- **stepOver/stepInto**: DAP rejection → `{ success: false, error }` (not thrown)
- **stepOut**: Grace window (5s) timeout → `{ success: true, state: RUNNING, data: { pending: true, message: 'still executing' } }` (L368-394); `_executeStepOperation` rejection → `{ success: false, error }` + sets state to `SessionState.ERROR` (L396-406)

### Breakpoint scenarios (L409-461)
- No proxy → queued, unverified (L410-419)
- DAP returns `verified: false` → propagated (L421-437)
- Empty DAP response → `verified: false` (L439-449)
- DAP network error → caught, logged, returns unverified (L451-460)

### Variables/StackTrace/Scopes (L463-589)
- No proxy → `[]` for all
- Not paused → `[]` for variables and scopes
- Missing `stackFrames` in response → throws `'did not include stack frames'` (L525-536) — enforces issue #124 fix
- StackTrace network failure propagates (L539-545)
- Malformed scopes → `[]`

### `evaluateExpression` (L591-793)
- No proxy → `{ success: false, error: 'No active debug session' }`
- DAP evaluation error (empty result) → `{ success: true, result: '' }` — DAP success even with semantic error
- Network failure → `{ success: false, error: 'Request failed' }`
- Syntax error mapping: `SyntaxError` in message → friendly `'Syntax error in expression'`
- Timeout override (issue #142, L731-793):
  - `stackTrace` pre-request uses default timeout (2-arg call)
  - `evaluate` gets `{ timeoutMs }` as third arg
  - Non-positive/non-finite timeout → `{ success: false, error: 'timeout' }` without DAP calls
  - Timeout clamped to 600000ms with `mockLogger.warn`
  - Timed-out evaluate error → hint about `'larger timeout'` arg

### `startDebugging` success/error (L796-1150)
- Dry run timeout → `{ success: false, error: 'Dry run timed out' }` (L797-821)
- Dry run already completed → immediate `{ success: true, data: { dryRun: true } }` without waiting (L823-848)
- Proxy creation failure → `{ success: false, error: 'Port allocation failed' }`
- Launch failure → `{ success: false, error: 'Failed to launch debuggee' }`
- Proxy log tail captured on init failure (L876-897): reads `proxy-{sessionId}.log`, includes tail in error log
- Log read failure → logged as `'Failed to read proxy log'`
- Policy-based handshake: `performHandshake` called; `isSessionReady` gate; timeout warning after 30s (fake timers)

### `waitForDryRunCompletion` (L1153-1223)
- Already completed → immediate `true`, no `once` listener
- `dry-run-complete` event fires → `true`; `removeListener` called
- Poll detects completion during timeout window → `true`
- Timeout without completion → `false`

### `_executeStepOperation` (L1225-1270)
- No proxy → `{ success: false, error: 'Proxy manager unavailable' }`
- `stopped` event fires → `{ success: true, data: { message: 'Step completed.' } }`; `off` cleanup called

### `attachToProcess` (L1363-1837)
- Thread discovery: prefers thread named `'main'`; falls back to first thread
- Zero threads for entire verification window → `{ success: false, state: ERROR, error: 'no threads reported...zero threads...verifyTimeout' }` + proxy stopped (issue #124 fix)
- Threads request keeps throwing → same failure shape with last error message
- DAP failure response (no `body`) → error contains `'Child session not ready'`
- `performHandshake` called with `{ sessionId, scriptPath: 'attach://remote', dapLaunchArgs: { ..., __attachMode: true }, launchConfig }`
- Handshake failure tolerated; warns and continues
- Threads appear during verification window → success
- `verifyTimeout` option: non-positive → `{ success: false, error: 'verifyTimeout' }` without proxy start; caller value used over default; larger value allows slow targets
- `verifyTimeout` NOT leaked into adapter attach args (L1719-1743)
- `stopOnEntry: false` → skips thread discovery
- Ruby `pauseAfterAttach` policy: sends `pause` DAP request; tolerates `'already stopped'` error
- Java: no post-attach pause

### Attach mode detection (L1839-1973)
- `request: 'attach'` → `transformAttachConfig` called, not `transformLaunchConfig`
- `__attachMode: true` flag → same routing
- Attach mode: `program`/`cwd`/`args` NOT in config
- Adapter without `supportsAttach` → falls back to `transformLaunchConfig`
- `transformAttachConfig` throws → `mockLogger.warn` with `'transformAttachConfig failed'`

### Multi-breakpoint DAP aggregation (L1976-2450)
All BPs for same file sent in single `setBreakpoints` request. Removal of BPs from map causes correct subset to be re-sent. BPs from different files not cross-contaminated. `com.A.Foo` and `com.A$Foo` treated as separate sources. DAP response updates `verified`/`line`/`message` fields. `suspendPolicy` passed through when provided, omitted when absent.

### Disconnect/Detach (L2452-2563)
- No proxy → `{ success: false, error: 'No active debug session to detach from' }`
- `terminateProcess=false` → `disconnect` with `{ terminateDebuggee: false }` + `stop()`; message contains `'process still running'`
- Race condition (proxy nulled during disconnect) → success, `stop()` not called
- Disconnect failure → warn logged, `stop()` still called (graceful cleanup)
- `terminateProcess=true` → calls `closeSession`; message contains `'terminated process'`
- After detach: `state=STOPPED`, `sessionStore.update({ sessionLifecycle: TERMINATED })`
- `stop()` failure → `{ success: false, error }`
- Unknown session → `SessionNotFoundError` thrown

### `selectPolicy` (L2565-2598)
- `'dotnet'` and `DebugLanguage.DOTNET` → returns policy with `name='dotnet'`
- Dotnet `getStackTrace` filters `System.*` and `Microsoft.*` frames

### `listThreads` (L2601-2651)
- Returns mapped thread objects from DAP
- Empty/missing body → `[]`
- `TERMINATED` lifecycle → `SessionTerminatedError`
- Proxy not running or null → `ProxyNotRunningError`

### `pause` with threadId (L2653-2846)
- Explicit `threadId` → passed directly to DAP
- No `threadId` → discovers via `threads` request, uses first thread
- `threads` request fails → falls back to `threadId=0`
- Empty threads list → falls back to `threadId=0`
- Handles stopped arriving after/before/during pause response
- Grace window (5s): no stopped event → `{ success: true, state: RUNNING, data: { pending: true } }`
- Session terminates while waiting → `{ success: true, data: { message: 'Session ended' } }`
- Pause request itself fails → rejects with error

## Key Invariants Tested
1. Malformed DAP responses (missing `stackFrames`) must throw, not silently return empty
2. Zero threads on attach must fail, not silently succeed (issue #124)
3. `verifyTimeout` option controls attach verification window and must not leak to adapter
4. Evaluation timeout errors must include hint about `timeout` parameter
5. Multi-file breakpoint aggregation: per-file isolation is strict
6. MSVC toolchain detection: structured error with `.toolchainValidation` property
7. Pending step/pause: grace window timeout → success + `pending: true`, not failure