# tests\core\unit\session\session-manager-edge-cases.test.ts
@source-hash: 05407ea8ca787d49
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:49Z

## Purpose
Test suite covering edge cases and error scenarios for `SessionManager`, including session creation edge cases, DAP operation failures, and session closing error handling.

## Test Structure

### Top-level describe: `SessionManager - Edge Cases and Error Scenarios` (L9–343)

**Setup (L14–32):**
- Uses `vi.useFakeTimers({ shouldAdvanceTime: true })` in `beforeEach`
- Instantiates `SessionManager` with config `{ logDirBase: '/tmp/test-sessions', defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true } }`
- Teardown resets timers, clears mocks, and calls `dependencies.mockProxyManager.reset()`

### Session Creation Edge Cases (L34–66)
- **L35–43**: Verifies `executablePath` is stored and retrievable via `getSession`
- **L45–55**: Creates 3 concurrent sessions and asserts all IDs are unique (Set size == array length)
- **L57–65**: Default session name matches pattern `/session-[a-f0-9]+/` (SessionStore format)

### Continue Method Error Handling (L68–87)
- **L69–86**: After starting debugging and simulating a stopped event, overrides `sendDapRequest` to reject; asserts `sessionManager.continue()` propagates the rejection with `'DAP request failed'`

### Error Scenarios in DAP Operations (L89–296)
- **L90–112**: `getVariables` with `sendDapRequest` rejecting → returns `[]`, logs error with `'Error getting variables'`
- **L114–136**: `getVariables` with `sendDapRequest` resolving `{}` (no body) → returns `[]`, warns with `'No variables in response body'`
- **L138–160**: `getStackTrace` with `sendDapRequest` rejecting → propagates rejection (`'Timeout'`), logs error with `'Error getting stack trace'`
- **L162–182**: `getStackTrace` with `sendDapRequest` resolving `{ success: false, message: "Child session not ready…" }` → rejects with `'Child session not ready'` (issue #124)
- **L184–204**: `getStackTrace` with `sendDapRequest` resolving `{ body: null }` → rejects with `'did not include stack frames'`, warns with `'No stackFrames in response body'`
- **L206–224**: `getLocalVariables` when stack trace fails (`success: false`) → propagates rejection `'Child session not ready'` (issue #124)
- **L226–246**: `getStackTrace` when `getCurrentThreadId` returns `null` → returns `[]`, warns with `'No effective thread ID to use'`
- **L248–270**: `getScopes` with `sendDapRequest` rejecting → returns `[]`, logs error with `'Error getting scopes'`
- **L272–296**: `getScopes` with response body `{ scopes: null }` → returns `[]`, warns with `'No scopes in response body'`

### Session Closing Error Cases (L299–342)
- **L300–320**: `closeSession` when `proxyManager.stop` rejects → returns `true`, session removed from store, logs error with `'Error stopping proxy'` and `'Stop failed'`
- **L322–329**: `closeSession('non-existent-id')` → returns `false`, warns with `'Session not found: non-existent-id'`
- **L331–341**: `closeSession` when no debugging was started (proxy undefined) → returns `true`, session removed

## Key Patterns
- All DAP error tests follow: create session → `startDebugging` → `runAllTimersAsync` → `simulateStopped` → override `sendDapRequest` → assert behavior
- `sendDapRequest` is overridden directly on `dependencies.mockProxyManager` as a `vi.fn()` mock
- `simulateStopped(threadId, reason)` is used to put session in paused state before DAP operations
- `simulateEvent('stopped', threadId, reason)` is an alternate form used once (L236)
- Issue #124 referenced in comments at L153–154, L174–175 — governs that stack trace errors must surface, not silently return empty arrays

## Dependencies
- `SessionManager`, `SessionManagerConfig` from `src/session/session-manager.js`
- `DebugLanguage` from `@debugmcp/shared` (using `DebugLanguage.MOCK` throughout)
- `createMockDependencies` from local `session-manager-test-utils.js` — provides `mockProxyManager`, `mockLogger`
