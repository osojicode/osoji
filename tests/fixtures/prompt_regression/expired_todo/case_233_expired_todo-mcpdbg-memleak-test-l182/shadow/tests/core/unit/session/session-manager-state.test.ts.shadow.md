# tests\core\unit\session\session-manager-state.test.ts
@source-hash: 61a1e891ab3cbbb4
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:18Z

## SessionManager State Machine Integrity Tests

Unit test suite validating the state machine behavior of `SessionManager`, covering valid state transitions, invalid operation rejection, and error-state consistency.

### Test Suite Structure
- **Suite**: `SessionManager - State Machine Integrity` (L10–108)
- **Setup** (L15–27): Uses `vi.useFakeTimers`, constructs `dependencies` via `createMockDependencies()`, configures `SessionManager` with `logDirBase: '/tmp/test-sessions'` and default DAP launch args (`stopOnEntry: true`, `justMyCode: true`).
- **Teardown** (L29–33): Restores real timers, clears mocks, resets `mockProxyManager`.

### Test Cases

#### 1. Valid State Transitions (L35–60)
Validates the full happy-path lifecycle:
- `createSession` → `CREATED`
- `startDebugging` immediately transitions session to `INITIALIZING` (L43, checked synchronously before awaiting)
- After timers flush and promise resolves → `PAUSED` (due to `stopOnEntry: true` default, L48–49)
- `continue` → `RUNNING` (L51–55); the `continued` event from the proxy is a no-op (state already set by `continue` call)
- `closeSession` → session removed entirely from store (L57–59)

#### 2. Invalid Operation Rejection (L62–86)
Validates that the manager rejects operations incompatible with current state:
- `stepOver` on `CREATED` (proxy not started) → throws `ProxyNotRunningError` (L69)
- `stepOver` when `RUNNING` (started with `stopOnEntry: false`) → returns `{ success: false, error: 'Not paused' }` (L78–80)
- `continue` when `RUNNING` → returns `{ success: false, error: 'Not paused' }` (L83–85)

#### 3. Error State Consistency (L88–108)
Validates that errors propagate correctly to session state:
- After `startDebugging` and timer flush, `continued` event is a no-op (state stays `PAUSED`, L98–99)
- `simulateError` → session transitions to `ERROR` state (L104)
- `proxyManager` is cleared from session (`undefined`, L105)
- Proxy's `stop` is called exactly once to properly reap it, not just dereference (L106–107); references issue #122

### Key Behavioral Contracts Tested
| Scenario | Expected Outcome |
|---|---|
| `stepOver` before proxy running | Throws `ProxyNotRunningError` |
| `stepOver`/`continue` while RUNNING | Returns `{ success: false, error: 'Not paused' }` |
| `continued` event while PAUSED | No-op; state stays PAUSED |
| Proxy error event | Session → ERROR, proxy stopped, proxyManager cleared |
| `closeSession` | Session removed from store |

### Dependencies
- `createMockDependencies` (from `session-manager-test-utils.js`): provides `mockProxyManager` with `simulateStopped`, `simulateEvent`, `simulateError`, `stopCalls`, and `reset` methods.
- `SessionManager` / `SessionManagerConfig`: production class under test.
- `DebugLanguage.MOCK`: test-only language enum value for safe mock execution.
- `SessionState`: enum with `INITIALIZING`, `PAUSED`, `RUNNING`, `ERROR` states.
- `ProxyNotRunningError`: typed error expected on pre-start operations.