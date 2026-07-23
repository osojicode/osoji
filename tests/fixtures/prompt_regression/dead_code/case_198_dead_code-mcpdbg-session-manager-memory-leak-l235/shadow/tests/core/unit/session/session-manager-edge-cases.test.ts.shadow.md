# tests\core\unit\session\session-manager-edge-cases.test.ts
@source-hash: 05407ea8ca787d49
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:09Z

## SessionManager Edge Cases and Error Scenarios Tests

Unit test suite covering edge cases, error handling, and failure scenarios for `SessionManager`. Tests focus on boundary conditions not covered by happy-path tests.

### Test Structure

**Top-level suite:** `SessionManager - Edge Cases and Error Scenarios` (L9)

Uses `beforeEach` (L14–26) to set up:
- Fake timers with `shouldAdvanceTime: true`
- Mock dependencies via `createMockDependencies()`
- `SessionManagerConfig` with `logDirBase: '/tmp/test-sessions'`, `stopOnEntry: true`, `justMyCode: true`
- Fresh `SessionManager` instance

Uses `afterEach` (L28–32) to restore real timers, clear mocks, and reset `mockProxyManager`.

### Describe Blocks and Test Cases

#### Session Creation Edge Cases (L34–66)
- **L35–43**: `should use provided executable path` — verifies `executablePath` is stored on the managed session via `getSession()`.
- **L45–55**: `should generate unique session IDs` — creates 3 concurrent sessions via `Promise.all`, checks IDs in a `Set` for uniqueness.
- **L57–65**: `should set default session name if not provided` — asserts `session.name` matches `/session-[a-f0-9]+/` (SessionStore ID format).

#### Continue Method Error Handling (L68–87)
- **L69–86**: `should throw error when continue DAP request fails` — overrides `sendDapRequest` with a rejected mock after `simulateStopped(1, 'entry')`, expects `sessionManager.continue(session.id)` to reject with `'DAP request failed'`.

#### Error Scenarios in DAP Operations (L89–296)
- **L90–112**: `getVariables` — DAP throws → returns `[]`, logs `error` with `'Error getting variables'`.
- **L114–136**: `getVariables` — DAP returns `{}` (no body) → returns `[]`, logs `warn` with `'No variables in response body'`.
- **L138–160**: `getStackTrace` — DAP throws `'Timeout'` → rejects (does NOT return empty array, per issue #124), logs `error` with `'Error getting stack trace'`.
- **L162–182**: `getStackTrace` — DAP returns `{ success: false, message: "Child session not ready for 'stackTrace'..." }` → rejects with `'Child session not ready'`.
- **L184–204**: `getStackTrace` — DAP returns `{ body: null }` → rejects with `'did not include stack frames'`, logs `warn` with `'No stackFrames in response body'`.
- **L206–224**: `getLocalVariables` — stack trace fails (same `success: false` shape) → rejects with `'Child session not ready'` (propagates through `getLocalVariables`).
- **L226–246**: `getStackTrace` with no thread ID — `simulateEvent('stopped', 1, 'entry')` then `getCurrentThreadId` mocked to return `null` → returns `[]`, logs `warn` with `'No effective thread ID to use'`. *Note: this test expects `[]` return instead of a throw, contrasting with issue #124 behavior.*
- **L248–270**: `getScopes` — DAP throws `'Invalid frame'` → returns `[]`, logs `error` with `'Error getting scopes'`.
- **L272–296**: `getScopes` — DAP returns `{ body: { scopes: null } }` → returns `[]`, logs `warn` with `'No scopes in response body'`.

#### Session Closing Error Cases (L299–342)
- **L300–320**: `closeSession` when proxy `stop()` throws → returns `true`, session removed from store, logs `error` with `'Error stopping proxy'` and message `'Stop failed'`.
- **L322–329**: `closeSession` with non-existent ID → returns `false`, logs `warn` with `'Session not found: non-existent-id'`.
- **L331–341**: `closeSession` when proxy is `undefined` (no `startDebugging` called) → returns `true`, session removed.

### Key Patterns
- Common setup: `createSession` → `startDebugging` → `vi.runAllTimersAsync()` → `simulateStopped(1, 'entry')` → override `sendDapRequest` with mock.
- Issue #124 referenced in three tests (L154, L175, L184): DAP stack trace failures must propagate as errors, not silently return empty arrays. Except the "no thread ID" path (L226–246), which legitimately returns `[]`.
- Error message assertions use `expect.stringContaining(...)` for flexibility.
- Logger error calls for proxy stop error (L316–319) pass the error **message string** as 2nd arg, not the `Error` object — contrast with other error tests that use `expect.any(Error)`.

### Dependencies
- `SessionManager`, `SessionManagerConfig` from `../../../../src/session/session-manager.js`
- `DebugLanguage` from `@debugmcp/shared`
- `createMockDependencies` from `./session-manager-test-utils.js` (provides `mockProxyManager`, `mockLogger`)
