# tests\core\unit\session\session-manager-dry-run.test.ts
@source-hash: 77e4903f7c161e84
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:39Z

## Purpose
Unit test suite focused exclusively on dry run race condition and timing behavior in `SessionManager`. Tests verify that `startDebugging` with `dryRunSpawn=true` correctly waits for, times out on, and cleans up after the `dry-run-complete` event.

## Test Suite Structure
Single `describe` block: `'SessionManager - Dry Run Race Condition Tests'` (L6), with a nested `describe` block: `'Dry Run Timing Issues'` (L31).

### Setup / Teardown
- `beforeEach` (L11–23): Uses `vi.useFakeTimers({ shouldAdvanceTime: true })`, creates mock dependencies via `createMockDependencies()`, instantiates `SessionManager` with `logDirBase: '/tmp/test-sessions'` and default DAP args (`stopOnEntry: true`, `justMyCode: true`).
- `afterEach` (L25–29): Restores real timers, clears mocks, and resets `mockProxyManager`.

### Test Cases

**1. `should wait for dry run completion beyond 500ms` (L32–78)**
- Overrides `mockProxyManager.start` to emit `dry-run-complete` after 1000ms (a delay deliberately longer than any legacy 500ms threshold).
- Advances fake timers by 1000ms, then awaits `startDebugging`.
- Asserts: duration ≥ 1000ms and < 2500ms, `result.success === true`, `result.state === SessionState.STOPPED`, `result.data.dryRun === true`, and `result.data.message` contains `'Dry run spawn command logged'`.

**2. `should timeout gracefully if dry run never completes` (L80–131)**
- Creates a second `SessionManager` with `dryRunTimeoutMs: 2000` (L83–86).
- Overrides `mockProxyManager.start` to never emit `dry-run-complete`.
- Advances timers by `testTimeout` (2000ms).
- Asserts: `result.success === false`, `result.error` contains `'timed out'` and `'2000ms'`.

**3. `should handle dry run completing before event listener setup` (L133–174)**
- Overrides start to emit via `process.nextTick` — a race condition simulation where the event fires before the listener is attached.
- Uses `vi.runAllTimersAsync()` to flush microtasks/timers.
- Asserts: `result.success === true`, `result.state === SessionState.STOPPED`, `result.data.dryRun === true`.

**4. `should handle dry run with very fast completion` (L176–218)**
- Emits `dry-run-complete` after 10ms.
- Advances timers by 10ms.
- Asserts: duration < 100ms (no unnecessary waiting), success, and `dryRun === true`.

**5. `should clean up event listeners properly on timeout` (L220–269)**
- Creates `SessionManager` with `dryRunTimeoutMs: 1000`.
- Spies on `mockProxyManager.once` and `mockProxyManager.removeListener`.
- Never emits `dry-run-complete`.
- Asserts: operation fails with `'timed out'`, `once` was called with `'dry-run-complete'`, and `removeListener` was called with `'dry-run-complete'` — confirming cleanup on timeout.

## Key Contracts Under Test
- `SessionManager.startDebugging(sessionId, scriptPath, args, env, dryRunSpawn=true)` must await the `dry-run-complete` event from the proxy manager.
- The proxy manager emits `dry-run-complete` with `(pythonPath, scriptPath)` arguments.
- On timeout (configurable via `dryRunTimeoutMs`), the method must remove the `dry-run-complete` listener and return `{ success: false, error: '...timed out...Xms...' }`.
- On success, returns `{ success: true, state: SessionState.STOPPED, data: { dryRun: true, message: 'Dry run spawn command logged...' } }`.

## Dependencies
- `SessionManager`, `SessionManagerConfig` from `src/session/session-manager.js`
- `SessionState`, `DebugLanguage` from `@debugmcp/shared`
- `createMockDependencies` from `./session-manager-test-utils.js` — provides `mockProxyManager` with `start`, `once`, `removeListener`, `emit`, `startCalls`, `reset`, and `_isRunning` fields.

## Notable Patterns
- Tests directly mutate `mockProxyManager.start` with `vi.fn()` overrides per test, allowing fine-grained control of emission timing.
- The `_isRunning` flag is set via `unknown` cast: `(mockProxyManager as unknown as { _isRunning: boolean })._isRunning = true` — necessary because the field is private/internal.
- The `dryRunTimeoutMs` config option on `SessionManagerConfig` enables shorter timeouts for test speed.
- Fake timers with `shouldAdvanceTime: true` allow `Date.now()` to reflect elapsed time even in fake timer mode, enabling duration assertions.
