# tests\core\unit\session\session-manager-integration.test.ts
@source-hash: a0ff478c24568c04
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:58Z

## SessionManager Integration Tests

Integration test suite for `SessionManager` covering event handling, logger integration, and session store behavior. Uses vitest with fake timers and mock dependencies from the shared test utilities.

### Test Structure

**Suite:** `SessionManager - Integration Tests` (L9–186)

**Setup (L14–32):**
- `beforeEach`: Activates fake timers (`shouldAdvanceTime: true`), instantiates `createMockDependencies()`, builds `SessionManagerConfig` with `logDirBase: '/tmp/test-sessions'` and `defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true }`, then constructs a fresh `SessionManager`.
- `afterEach`: Restores real timers, clears all mocks, resets `mockProxyManager`.

---

### Sub-suites & Key Tests

#### `Event Handling` (L34–78)

- **`should forward ProxyManager events correctly`** (L35–56):  
  Creates session → starts debugging → runs all timers → simulates `stopped`/`continued`/`terminated` proxy events.  
  Asserts: `stopped` event transitions session to `SessionState.PAUSED`; `continued` event while already PAUSED does **not** flip state back to RUNNING (regression guard, comment L49); `terminated` → `SessionState.STOPPED` + proxy `stopCalls === 1` (issue #122 guard, L54–55).

- **`should handle auto-continue for stopOnEntry=false`** (L58–77):  
  Starts debugging with `{ stopOnEntry: false }`. Simulates `stopped` with reason `'entry'`. Asserts logger received message containing `'Auto-continuing (stopOnEntry=false)'`.

#### `Logger Integration` (L80–140)

- **`should log all major operations`** (L81–103):  
  Checks `logger.info` called with `'Created new session'` after `createSession`; called with `/[Aa]ttempting to start debugging/` + `undefined` (no dapLaunchArgs) after `startDebugging`; called with `'Closing debug session'` after `closeSession`.

- **`does not log env values passed in dapLaunchArgs`** (L105–121):  
  Security/privacy test. Passes `env: { GITHUB_PAT: 'github_pat_SESSIONLEAK1' }` in dapLaunchArgs. Asserts that concatenated JSON of all `logger.info` calls does **not** contain the secret value `'github_pat_SESSIONLEAK1'`.

- **`should log errors appropriately`** (L123–139):  
  Sets `mockProxyManager.shouldFailStart = true` before `startDebugging`. Asserts `logger.error` was called and one call contains `'Detailed error in startDebugging'`.

#### `Integration with SessionStore` (L142–185)

- **`should persist sessions correctly`** (L143–164):  
  Creates two sessions with `name` properties. Asserts `getAllSessions()` returns length 2 and contains both sessions with correct `id` and `name`.

- **`should update session state in store`** (L166–184):  
  Creates session, records `initialUpdatedAt`, advances fake timers by 100ms, starts debugging, runs all timers. Asserts state is `SessionState.PAUSED` (because default config has `stopOnEntry: true` and mock immediately emits stopped event) and `updatedAt` has advanced.

---

### Dependencies & Patterns

- **`createMockDependencies()`** (imported from `./session-manager-test-utils.js`): Provides `mockProxyManager` (with `simulateEvent`, `shouldFailStart`, `stopCalls`, `reset`) and `logger` (vi mock with `info`, `error` spies).
- **`DebugLanguage.MOCK`**: Used for all session creation; triggers mock proxy behavior.
- **`vi.runAllTimersAsync()`**: Required after `startDebugging` to allow async event propagation from the mock proxy.
- **Fake timers** with `shouldAdvanceTime: true` allow deterministic `updatedAt` comparison.
- `startDebugging` accepts optional 4th arg `dapLaunchArgs` (override `stopOnEntry`, `env`, etc.).
