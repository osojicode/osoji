# tests\core\unit\session\session-manager-multi-session.test.ts
@source-hash: f8b0db3523041151
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:50Z

## Purpose
Unit tests for `SessionManager` multi-session management capabilities: concurrent session creation, state isolation between sessions, and bulk session teardown via `closeAllSessions`.

## Test Suite Structure

**Suite:** `SessionManager - Multi-Session Management` (L10–171)

### Setup / Teardown (L15–33)
- `beforeEach`: Uses `vi.useFakeTimers({ shouldAdvanceTime: true })`, creates mock dependencies via `createMockDependencies()`, constructs `SessionManagerConfig` with `logDirBase: '/tmp/test-sessions'` and `defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true }`, then instantiates `SessionManager`.
- `afterEach`: Restores real timers, clears all mocks, resets `dependencies.mockProxyManager`.

### Test Cases

#### 1. `should manage multiple concurrent debug sessions` (L35–70)
- Creates 3 sessions with `DebugLanguage.MOCK`.
- Asserts `getAllSessions()` returns 3 items (L54).
- Starts all 3 sessions concurrently using `Promise.all` + `vi.runAllTimersAsync()`.
- Asserts all start results have `success: true` (L64).
- Asserts each session is in `SessionState.PAUSED` (L67–69).

#### 2. `should isolate session states properly` (L72–106)
- Overrides `proxyManagerFactory.create` to return different `MockProxyManager` instances (`mockProxyManager1`, `mockProxyManager2`) using a counter (L78–80).
- Creates and starts 2 sessions.
- Simulates `stopped` on session 1's proxy (L99), calls `continue(session1.id)` (L100), simulates `continued` event (L101).
- Asserts session 1 is `SessionState.RUNNING` and session 2 remains `SessionState.PAUSED` (L104–105).

#### 3. `should handle closeAllSessions with active sessions` (L108–130)
- Creates and starts 2 sessions.
- Calls `sessionManager.closeAllSessions()`.
- Asserts both sessions are removed from the store (undefined via `getSession`) (L127–128).
- Asserts `dependencies.mockProxyManager.stopCalls` equals 2 (L129) — verifying each proxy was stopped.

#### 4. `should handle empty session list in closeAllSessions` (L132–142)
- No sessions created; calls `closeAllSessions()` immediately.
- Asserts `mockLogger.info` called with `'Closing all debug sessions (0 active)'` substring (L136–138).
- Asserts `mockLogger.info` called with exact string `'All debug sessions closed'` (L139–141).

#### 5. `should handle errors in individual sessions during closeAllSessions` (L144–170)
- Creates and starts 2 sessions.
- Retrieves `session1.proxyManager` and overrides its `stop` method to reject with `Error('Stop failed')` (L161–163).
- Calls `closeAllSessions()` and asserts both sessions are undefined afterwards (L168–169), confirming error resilience.

## Key Dependencies
- `SessionManager` + `SessionManagerConfig` from `../../../../src/session/session-manager.js` — system under test.
- `DebugLanguage`, `SessionState` from `@debugmcp/shared` — enums for session configuration and state assertions.
- `MockProxyManager` from `../../../test-utils/mocks/mock-proxy-manager.js` — fake proxy with `simulateStopped`, `simulateEvent`, `stop`, `stopCalls` counter, `reset`.
- `createMockDependencies` from `./session-manager-test-utils.js` — factory returning `{ mockProxyManager, proxyManagerFactory, mockLogger, ... }`.

## Notable Patterns
- **Factory override pattern** (L78–80): `proxyManagerFactory.create` is replaced mid-test to return distinct `MockProxyManager` instances, enabling per-session proxy isolation testing.
- **Direct proxy mutation** (L162): Reaches into `session.proxyManager` to override `stop`, testing `closeAllSessions` error resilience without a factory-level hook.
- **`vi.runAllTimersAsync()`** is required after `startDebugging` calls to flush timer-based async flows in the mock environment.
- `stopCalls` counter on `mockProxyManager` validates that `closeAllSessions` invokes stop on every proxy (L129).
