# src\session\session-manager-core.ts
@source-hash: b2962b7402a96b8b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:16Z

## SessionManagerCore (L66-490)

Abstract base class providing core session lifecycle management, state transitions, proxy event wiring, and dependency injection scaffolding for debug sessions. Concrete subclasses must implement `handleAutoContinue`.

---

### Purpose
Central orchestration hub for creating, tracking, and closing debug sessions. Manages the bridge between the session store (metadata/state) and proxy managers (DAP communication). Wires proxy events (`stopped`, `continued`, `terminated`, `exited`, `error`, `exit`, `adapter-configured`, `dry-run-complete`) to session state transitions with nuanced first-stop auto-continue logic.

---

### Key Interfaces & Types

#### `CustomLaunchRequestArguments` (L25-28)
Extends `DebugProtocol.LaunchRequestArguments` with `stopOnEntry?: boolean` and `justMyCode?: boolean`. Used as the canonical launch args type throughout the class.

#### `DebugResult` (L30-39)
Standard return shape for debug operations: `success`, `state`, optional `error`, `data`, `canContinue`, `errorType` (machine-readable, e.g. `'PythonNotFoundError'`), `errorCode` (e.g. `-32602`).

#### `SessionManagerDependencies` (L44-52)
Full DI container: `fileSystem`, `networkManager`, `logger`, `proxyManagerFactory`, `sessionStoreFactory`, `environment`, `adapterRegistry`.

#### `SessionManagerConfig` (L57-61)
Optional config: `logDirBase` (defaults to `os.tmpdir()/debug-mcp-server/sessions`), `defaultDapLaunchArgs` (defaults `stopOnEntry:false`, `justMyCode:true`), `dryRunTimeoutMs` (defaults `10000`).

---

### Class: `SessionManagerCore` (L66-490)

**Protected fields:**
- `sessionStore: SessionStore` — primary session registry
- `logDirBase: string` — filesystem path for session logs
- `logger`, `fileSystem`, `networkManager`, `environment` — injected infrastructure
- `proxyManagerFactory`, `sessionStoreFactory` — injected factories
- `defaultDapLaunchArgs`, `dryRunTimeoutMs` — runtime defaults
- `sessionEventHandlers: WeakMap<ManagedSession, Map<string, handler>>` (L81) — tracks named event handlers per session for deterministic cleanup; WeakMap prevents memory leaks on session GC

**Public field:**
- `adapterRegistry: IAdapterRegistry` — exposed for subclass/external adapter policy queries

---

### Constructor (L86-108)
Injects all dependencies, initializes `sessionStore` via factory, resolves `logDirBase`, calls `fileSystem.ensureDirSync(logDirBase)`.

---

### Key Methods

#### `createSession(params)` (L110-119)
Delegates to `sessionStore.createSession`. Returns `DebugSessionInfo`.

#### `_updateSessionState(session, newState)` (L129-142)
Internal state transition: calls `sessionStore.updateState` (legacy), then `mapLegacyState` to derive `lifecycle`/`execution`, then `sessionStore.update` with both. Guards against no-op transitions.

#### `getSessionPolicy(sessionId)` (L147-150)
Returns `AdapterPolicy` for a session's language via `sessionStore.selectPolicy`.

#### `getSession(sessionId)` (L152-154)
Returns `ManagedSession | undefined` from store.

#### `getAllSessions()` (L156-158)
Returns all `DebugSessionInfo[]` from store.

#### `closeSession(sessionId)` (L160-198)
Full teardown: (1) cleanup proxy event listeners, (2) `proxyManager.stop()`, (3) set state `STOPPED`, (4) set lifecycle `TERMINATED`, (5) `sessionStore.remove`. Returns `false` if session not found.

#### `closeAllSessions()` (L200-207)
Iterates all managed sessions, calls `closeSession` sequentially.

#### `setupProxyEventHandlers(session, proxyManager, effectiveLaunchArgs)` (L209-444)
Wires 8 named event handlers onto `proxyManager` and stores them in `sessionEventHandlers` WeakMap. **Critical logic:**

- **`stopped` handler** (L237-292): Implements first-stop auto-continue heuristic.
  - `firstStopMayBeNonEntry` flag (L227-234): set `true` if adapter policy has `pauseAfterChildAttach === true` (e.g., js-debug). Allows non-`entry` reason to trigger auto-continue on first stop.
  - Attach sessions (`request === 'attach'` or `__attachMode === true`) are **never** auto-continued.
  - `userBreakReasons` set (L255-261): `breakpoint`, `function breakpoint`, `data breakpoint`, `instruction breakpoint`, `exception` — always stay paused even on first stop.
  - Auto-continue path: sets state `PAUSED` synchronously before calling `handleAutoContinue` (required by continue() precondition).
  - Sets `session.firstStopHandled = true` after first stop.

- **`continued` handler** (L297-319): Guards against stale continued events — if already `PAUSED`, ignores the event (prevents re-continuing after a breakpoint stop).

- **`terminated` / `exited` handlers** (L324-374): Set state `STOPPED`, cleanup listeners, `session.proxyManager = undefined`, then call `proxyManager.stop()` to reap process (issue #122, Windows orphan fix).

- **`adapter-configured` handler** (L377-385): Sets state `RUNNING` if `!stopOnEntry`.

- **`dry-run-complete` handler** (L387-399): Sets state `STOPPED`. Conditionally clears `proxyManager` only if `_dryRunHandlerSetup` flag is absent on session (allows dry-run waiters to still reference proxy).

- **`error` handler** (L401-419): Sets state `ERROR`, cleanup listeners, clears proxyManager, reaps process.

- **`exit` handler** (L422-439): If not already `STOPPED`/`ERROR`: clean exit (code 0 or `null`+no signal) → `STOPPED`; otherwise → `ERROR`. Always cleans up listeners and clears proxyManager.

#### `cleanupProxyEventHandlers(session, proxyManager)` (L446-476)
Removes all stored event listeners from `proxyManager` via `removeListener`, deletes entry from WeakMap. Double-cleanup safe (checks `has` before proceeding).

#### `_testOnly_cleanupProxyEventHandlers` (L481-483)
Public test accessor for `cleanupProxyEventHandlers`. Annotated `@internal`.

#### `handleAutoContinue(sessionId)` (L489) — abstract
Must be implemented by subclass. Called when `stopOnEntry=false` and first stop reason warrants auto-continue.

---

### Architectural Patterns
- **Dependency injection**: All external dependencies injected via constructor — no direct `new` calls for I/O or network.
- **WeakMap for event handler tracking**: Prevents retention of session objects after removal; enables deterministic listener cleanup.
- **Dual state model**: Both legacy `SessionState` enum and new `SessionLifecycleState`/`executionState` are updated on every transition via `_updateSessionState`.
- **Proxy process reaping** (issue #122): `proxyManager.stop()` called on `terminated`, `exited`, and `error` events to prevent orphan processes on Windows.
- **Abstract subclass pattern**: Core is non-instantiable; subclass must provide `handleAutoContinue`.
