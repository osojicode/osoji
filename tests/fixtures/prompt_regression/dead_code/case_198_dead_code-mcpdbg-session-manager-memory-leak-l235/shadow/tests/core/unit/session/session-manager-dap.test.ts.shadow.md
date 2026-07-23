# tests\core\unit\session\session-manager-dap.test.ts
@source-hash: ed8bce5f8dd3ed6f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:53Z

## SessionManager DAP Operations Tests

Unit test suite validating DAP (Debug Adapter Protocol) operations in `SessionManager`, covering breakpoint management, step controls, variable inspection, and stack frame retrieval.

### File Structure
- **Outer suite**: `SessionManager - DAP Operations` (L11–400)
- **Setup/teardown**: `beforeEach` (L16–28) / `afterEach` (L30–34)
- **Helper**: `createPausedSession` (L36–52) — creates a session, starts debugging, simulates a `stopped` event at `threadId=1` with reason `entry`, and clears `dapRequestCalls`

### Test Groups

#### Breakpoint Management (L54–122)
- **Queue breakpoints before session starts** (L55–69): Verifies unverified breakpoints are queued and stored in `managedSession.breakpoints`
- **Send breakpoints to active session** (L71–96): After `startDebugging`, `setBreakpoint` emits a `setBreakpoints` DAP command and returns `verified: true`
- **Conditional breakpoints** (L98–121): `setBreakpoint` with a condition propagates `condition` in the DAP `setBreakpoints` args

#### Step Operations (L124–227)
- **Step over** (L125–138): `stepOver` sends DAP `next` with `{ threadId: 1 }`
- **Step into** (L140–150): `stepInto` sends DAP `stepIn` with `{ threadId: 1 }`
- **Step out** (L152–162): `stepOut` sends DAP `stepOut` with `{ threadId: 1 }`
- **Reject when not paused** (L164–182): Throws `ProxyNotRunningError` if proxy not started; returns `{ success: false, error: 'Not paused' }` if session is running (`stopOnEntry: false`)
- **Grace window timeout** (L184–207): When mock never emits `stopped`, advancing 6 seconds past the grace window resolves step with `{ success: true, data: { pending: true, message: ErrorMessages.stepStillRunning(5) } }`; session stays `RUNNING` until `simulateStopped` is eventually called
- **Termination during step** (L209–226): `terminated` event emitted during `next` command resolves step promise as `{ success: true }`

#### Variable Inspection (L229–283)
- **Fallback to Script/Global scope** (L230–283): When no `Local` scope is present, `getLocalVariables` falls back to the first available scope (`Script`) and returns its variables

#### Variable and Stack Inspection (L286–399)
- **Get variables** (L287–313): `getVariables(sessionId, 100)` sends `variables` with `{ variablesReference: 100 }` and returns mock variable `{ name: 'test_var', value: '42', type: 'int', expandable: false }`
- **Get stack trace** (L315–341): `getStackTrace` sends `stackTrace` with `{ threadId: 1 }` and returns mock frame `{ id: 1, name: 'main', file: 'test.py', line: 10 }`
- **Get scopes** (L343–368): `getScopes(sessionId, 1)` sends `scopes` with `{ frameId: 1 }` and returns mock scope `{ name: 'Locals', variablesReference: 100, expensive: false }`
- **Empty arrays when not paused** (L370–398): All inspection methods return `[]` when session is not started or in running state

### Key Dependencies
- `SessionManager` from `src/session/session-manager.ts` — system under test
- `createMockDependencies` from `./session-manager-test-utils.ts` — provides `mockProxyManager` with `simulateStopped`, `dapRequestCalls`, `sendDapRequest`, `reset`, and `emit` facilities
- `ErrorMessages.stepStillRunning(5)` from `src/utils/error-messages.ts` — expected message for grace window timeout
- `ProxyNotRunningError` from `src/errors/debug-errors.ts` — expected thrown error type
- `DebugLanguage.MOCK` / `SessionState` from `@debugmcp/shared`

### Patterns
- Fake timers with `shouldAdvanceTime: true` used throughout; `vi.runAllTimersAsync()` advances pending async timer chains
- `createPausedSession` shared helper avoids duplication of session setup across step/inspection tests
- `dapRequestCalls` array on mock proxy manager is manually reset between phases within individual tests
- Mock `sendDapRequest` is overridden per-test for edge cases (grace window, termination, scope fallback)