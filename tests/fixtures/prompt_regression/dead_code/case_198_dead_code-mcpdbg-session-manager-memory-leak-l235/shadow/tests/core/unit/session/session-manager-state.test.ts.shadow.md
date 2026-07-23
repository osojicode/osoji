# tests\core\unit\session\session-manager-state.test.ts
@source-hash: 61a1e891ab3cbbb4
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:12Z

## SessionManager State Machine Integrity Tests

Unit tests validating state machine transitions, invalid operation rejection, and error state handling for `SessionManager`.

### Test Suite Structure
Single `describe` block: `'SessionManager - State Machine Integrity'` (L10–109)

**Setup (L15–33):**
- `beforeEach`: Uses fake timers (`vi.useFakeTimers`), creates mock dependencies via `createMockDependencies()`, instantiates `SessionManager` with config `{ logDirBase: '/tmp/test-sessions', defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true } }`.
- `afterEach`: Restores real timers, clears mocks, resets `mockProxyManager`.

---

### Test Cases

**1. `should enforce valid state transitions` (L35–60)**
Exercises the full happy-path state machine:
- `createSession` → `startDebugging` → state immediately becomes `INITIALIZING` (L43)
- After `runAllTimersAsync` + `startPromise` resolves → state becomes `PAUSED` (L49) due to `stopOnEntry: true` default
- `continue()` call → state becomes `RUNNING` (L55); `simulateEvent('continued')` is a no-op after `continue` already sets state
- `closeSession()` → session removed from store (`getSession` returns `undefined`, L59)

**2. `should reject invalid operations based on state` (L62–86)**
Validates state-guarded operation rejection:
- `stepOver` on a `CREATED` session (proxy not running) throws `ProxyNotRunningError` (L69) — typed error, not generic
- `startDebugging` with `stopOnEntry: false` → session enters `RUNNING` state
- `stepOver` while `RUNNING` returns `{ success: false, error: 'Not paused' }` (L78–80)
- `continue` while `RUNNING` returns `{ success: false, error: 'Not paused' }` (L83–85)

**3. `should maintain state consistency during errors` (L88–108)**
Validates error resilience:
- After `startDebugging` resolves (stopOnEntry default=true → PAUSED)
- `simulateEvent('continued')` has no effect on PAUSED state (L99) — state remains `PAUSED`
- `simulateError(new Error('Runtime error'))` → state transitions to `SessionState.ERROR` (L104)
- `session.proxyManager` is `undefined` after error (L105)
- `mockProxyManager.stopCalls` equals `1` (L107) — proxy must be explicitly stopped (reaped), not just dereferenced; references issue #122

---

### Key Dependencies
- `SessionManager` / `SessionManagerConfig`: system under test from `src/session/session-manager.js`
- `DebugLanguage`, `SessionState`: shared enums from `@debugmcp/shared`
- `createMockDependencies`: test utility from `./session-manager-test-utils.js` — returns object with `mockProxyManager` (has `.simulateStopped()`, `.simulateEvent()`, `.simulateError()`, `.stopCalls`, `.reset()`)
- `ProxyNotRunningError`: typed error from `src/errors/debug-errors.js`

### Notable Patterns
- `vi.runAllTimersAsync()` is required to flush async DAP startup sequences after `startDebugging` (L45, L74, L95)
- `simulateStopped(1, 'entry')` at L52 simulates the DAP `stopped` event with threadId=1, reason='entry'; this appears redundant since `stopOnEntry: true` already puts session in PAUSED — possibly just reinforcing the stopped state before `continue()`
- Session state is accessed via `sessionManager.getSession(session.id)?.state` — optional chaining expected for existence checks
- The comment at L51 clarifies that `continue()` sets state to RUNNING before the DAP request, and the subsequent `continued` event is a no-op
