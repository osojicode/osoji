# tests\core\unit\session\session-manager-workflow.test.ts
@source-hash: e52ffab525c14c23
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:11Z

## SessionManager Workflow Tests

Integration-style unit tests for the `SessionManager` debug session lifecycle, covering complete workflows from session creation through termination. Tests verify correct event handling, state transitions, and proxy manager interactions.

### Test File Structure

- **Suite**: `SessionManager - Debug Session Workflow` (L9-240)
- **Nested Suite**: `Complete Debug Cycle` (L34-240)

### Setup / Teardown (L14-32)

- `beforeEach`: Activates fake timers (`shouldAdvanceTime: true`), builds `createMockDependencies()`, constructs a `SessionManagerConfig` with `logDirBase: '/tmp/test-sessions'` and `defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true }`, then instantiates `SessionManager`.
- `afterEach`: Restores real timers, clears all mocks, resets the mock proxy manager.

### Test Cases

#### Full Debug Workflow (L35-83)
Tests the canonical lifecycle: `createSession` → `startDebugging` → `setBreakpoint` → `stepOver` → `closeSession`.
- Verifies `session.state === SessionState.CREATED` after creation.
- Uses `vi.runAllTimersAsync()` to flush async proxy events.
- Asserts `startResult.success === true` and state transitions to `SessionState.PAUSED`.
- Validates breakpoint DAP request shape: `{ command: 'setBreakpoints', args: { breakpoints: [{ line: 15, condition: undefined }] } }`.
- Asserts `stepOver` succeeds; `closeSession` returns `true`; `getSession` returns `undefined` post-close.

#### Dry Run Workflow (L85-114)
Tests `startDebugging` with `dryRun=true` (5th argument).
- Expects `result.success === true`, `result.data.dryRun === true`, `result.state === SessionState.STOPPED`.
- Asserts no `'proxy exited before initialization'` error log.
- Confirms `mockProxyManager.startCalls[0].dryRunSpawn === true`.

#### stopOnEntry=false Workflow (L116-147)
Tests that passing `{ stopOnEntry: false }` in launch args flows through correctly.
- Registers a mock `'start'` event handler on `mockProxyManager` to emit `'adapter-configured'` via `setTimeout(10ms)` instead of a stopped event.
- Expects `result.state === SessionState.RUNNING`.
- Confirms `mockProxyManager.startCalls[0].stopOnEntry === false`.

#### Terminated Event During Startup (L149-179)
Overrides `mockProxyManager.start` to emit `'terminated'` via `process.nextTick`.
- Expects `result.success === true`.
- Expects logger info call containing `'terminated during startup'`.
- Asserts `mockProxyManager.stopCalls === 1` (proxy process must be reaped — issue #122).

#### Exited Event During Startup (L181-210)
Overrides `mockProxyManager.start` to emit `'exited'` with code `0` via `process.nextTick`.
- Expects `result.success === true`.
- Expects logger info containing `'exited during startup'`.
- Asserts `mockProxyManager.stopCalls === 1` (issue #122 compliance).

#### Exit Event During Startup (L212-239)
Overrides `mockProxyManager.start` to emit `'exit'` with code `1` and signal `'SIGKILL'` via `process.nextTick`.
- Expects `result.success === true`.
- Expects logger info containing `'proxy exited during startup'`.
- Note: Does **not** assert `stopCalls === 1` (unlike terminated/exited cases).

### Key Architectural Patterns
- **Fake Timers**: Required because `SessionManager` uses timeouts internally; `vi.runAllTimersAsync()` is called before awaiting `startPromise` to allow proxy events to propagate.
- **Mock Override Pattern**: Three tests override `mockProxyManager.start` with `vi.fn().mockImplementation(...)` to inject specific event sequences, setting `_isRunning` and pushing to `startCalls` to maintain mock state invariants.
- **issue #122 contract**: Natural termination events (`terminated`, `exited`) must trigger proxy cleanup (`stopCalls === 1`); `exit` event does not assert this.
