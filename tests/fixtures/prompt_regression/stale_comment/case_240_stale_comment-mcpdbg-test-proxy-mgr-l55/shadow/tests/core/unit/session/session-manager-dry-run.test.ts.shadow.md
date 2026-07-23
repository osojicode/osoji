# tests\core\unit\session\session-manager-dry-run.test.ts
@source-hash: 77e4903f7c161e84
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:35Z

## Purpose
Unit tests for `SessionManager` dry run race condition and timing behavior. Validates that `startDebugging` with `dryRunSpawn=true` correctly handles: delayed completion, timeout, early event emission (race condition), fast completion, and event listener cleanup.

## Test Suite Structure

**Suite:** `SessionManager - Dry Run Race Condition Tests` (L6–271)  
**Sub-suite:** `Dry Run Timing Issues` (L31–270)

### Setup (L11–29)
- Uses `vi.useFakeTimers({ shouldAdvanceTime: true })` to control async timing
- Instantiates `SessionManager` with `config = { logDirBase: '/tmp/test-sessions', defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true } }`
- Mock dependencies provided by `createMockDependencies()` (from `session-manager-test-utils.js`)
- `afterEach`: restores real timers, clears mocks, resets `mockProxyManager`

### Test Cases

#### 1. Slow dry run (1000ms delay) — L32–78
- Overrides `mockProxyManager.start` to emit `'dry-run-complete'` after 1000ms via `setTimeout`
- Calls `sessionManager.startDebugging(session.id, 'test.py', [], {}, true)`
- Advances fake timers by 1000ms with `vi.advanceTimersByTimeAsync(1000)`
- Asserts: `duration >= 1000`, `result.success === true`, `result.state === SessionState.STOPPED`, `result.data.dryRun === true`, `result.data.message` contains `'Dry run spawn command logged'`

#### 2. Timeout — never completes — L80–131
- Creates a separate `SessionManager` with `dryRunTimeoutMs: 2000` (L83–86)
- Overrides `mockProxyManager.start` to never emit `'dry-run-complete'`
- Advances fake timers by `testTimeout` (2000ms)
- Asserts: `duration >= 2000`, `result.success === false`, `result.error` contains `'timed out'` and `'2000ms'`

#### 3. Race condition — event before listener setup — L133–174
- Overrides `mockProxyManager.start` to emit `'dry-run-complete'` via `process.nextTick` (simulates emission before listener registration)
- Uses `vi.runAllTimersAsync()` to flush microtasks/timers
- Asserts: `result.success === true`, `result.state === SessionState.STOPPED`, `result.data.dryRun === true`
- Tests that `SessionManager` handles the case where `dry-run-complete` fires before the await handler is established

#### 4. Fast completion (10ms) — L176–218
- Overrides `mockProxyManager.start` to emit `'dry-run-complete'` after 10ms
- Advances fake timers by 10ms
- Asserts: `duration < 100` (no unnecessary delays), `result.success === true`, `result.state === SessionState.STOPPED`

#### 5. Listener cleanup on timeout — L220–269
- Creates `SessionManager` with `dryRunTimeoutMs: 1000`
- Spies on `mockProxyManager.once` and `mockProxyManager.removeListener`
- Never emits `'dry-run-complete'`; advances timers by `testTimeout`
- Asserts: timeout failure, `onceSpy` called with `('dry-run-complete', Function)`, `removeListenerSpy` called with `('dry-run-complete', Function)` — verifying no listener leak

## Key Behavioral Contracts Tested
- `startDebugging` waits for `'dry-run-complete'` event on `mockProxyManager`, not a fixed 500ms delay
- `dryRunTimeoutMs` config controls timeout duration
- On timeout: returns `{ success: false, error: '...timed out...Xms...' }`
- On success: returns `{ success: true, state: SessionState.STOPPED, data: { dryRun: true, message: 'Dry run spawn command logged...' } }`
- Listener is registered via `.once('dry-run-complete', ...)` and cleaned up via `.removeListener(...)` on timeout

## Dependencies
- `SessionManager` / `SessionManagerConfig` from `src/session/session-manager.js`
- `SessionState`, `DebugLanguage` from `@debugmcp/shared`
- `createMockDependencies` from `./session-manager-test-utils.js` — provides `mockProxyManager` with `.start`, `.emit`, `.once`, `.removeListener`, `.reset`, `.startCalls`
- `vitest` for test runner and fake timers