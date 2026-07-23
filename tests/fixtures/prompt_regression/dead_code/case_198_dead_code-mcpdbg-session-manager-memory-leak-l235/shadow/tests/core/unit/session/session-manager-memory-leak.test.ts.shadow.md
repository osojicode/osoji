# tests\core\unit\session\session-manager-memory-leak.test.ts
@source-hash: 769e4daa6b34eda2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:58Z

## SessionManager Memory Leak Prevention Tests

Unit test suite verifying that `SessionManager` properly cleans up event listeners on the `ProxyManager` to prevent memory leaks. All tests use `DebugLanguage.MOCK` and fake timers.

### Test Structure

**Suite:** `SessionManager - Memory Leak Prevention` (L10–350)

Three sub-suites:

---

#### `Event Listener Cleanup` (L35–216)

| Test | Lines | Purpose |
|---|---|---|
| Remove all event listeners on close | L36–73 | After `closeSession`, all 9 tracked event names have 0 listeners |
| No listener accumulation across sessions | L75–99 | 10 sequential create/start/close cycles yield 0 total listeners |
| Cleanup survives `stop()` throwing | L101–124 | Even if `proxyManager.stop()` rejects, listeners are still removed |
| Double close handled gracefully | L126–155 | Second `closeSession` resolves `false`; listener count stays 0 |
| Cleanup on unexpected `terminated` event | L157–185 | `simulateEvent('terminated')` → 0 listeners, state=`STOPPED`, `stopCalls===1` |
| Cleanup on unexpected `exit` event | L187–215 | `simulateExit(1,'SIGTERM')` → 0 listeners, state=`ERROR`, `stopCalls===0` |

**Tracked event names** (L48–50): `stopped`, `continued`, `terminated`, `exited`, `initialized`, `error`, `exit`, `adapter-configured`, `dry-run-complete`

---

#### `Cleanup Method Testing` (L218–268)

| Test | Lines | Purpose |
|---|---|---|
| Internal `_testOnly_cleanupProxyEventHandlers` | L219–241 | Calls private method via `as any` cast if present; verifies `stopped` count drops to 0 |
| Logging on cleanup | L243–267 | `debug` logs include `'Removing'` + `'listener'`; `info` logs include `'Cleanup complete'` or `'removed'` |

---

#### `Edge Cases` (L270–349)

| Test | Lines | Purpose |
|---|---|---|
| Cleanup with no handlers attached | L271–279 | `closeSession` before `startDebugging` resolves `true` (no crash) |
| Partial cleanup failure | L281–316 | `removeListener` throws for `'stopped'`; error is logged; other listeners still removed |
| Session removed from store after close | L318–335 | 5 sessions created, all closed → `getAllSessions().length === 0` |
| `getSession` returns undefined after close | L337–348 | Session is no longer retrievable after close |

---

### Setup / Teardown

- **`beforeEach`** (L15–27): Installs fake timers (`shouldAdvanceTime: true`), calls `createMockDependencies()`, builds `SessionManagerConfig` with `logDirBase: '/tmp/test-sessions'` and DAP launch args, constructs `SessionManager`.
- **`afterEach`** (L29–33): Restores real timers, clears all mocks, resets `mockProxyManager`.

### Key Dependencies

- `createMockDependencies` (from `session-manager-test-utils.js`) — provides `mockProxyManager` (mock EventEmitter with `listenerCount`, `eventNames`, `simulateEvent`, `simulateExit`, `stopCalls`, `stop`), `logger`.
- `SessionManager` — class under test; accepts `(config, dependencies)`.
- `DebugLanguage.MOCK`, `SessionState` — from `@debugmcp/shared`.

### Important Behavioral Contracts Tested

1. `terminated` event → session state becomes `SessionState.STOPPED`, `stop()` IS called once (force-kill path).
2. `exit` event → session state becomes `SessionState.ERROR`, `stop()` is NOT called (process already gone).
3. Listener cleanup is unconditional: happens even when `stop()` throws, even when `removeListener` partially throws.
4. `closeSession` returns `false` for an already-closed session (session no longer in store).
5. A private testing hook `_testOnly_cleanupProxyEventHandlers` may exist on `SessionManager`; tests guard its use with an existence check (L235).