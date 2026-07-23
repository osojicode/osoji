# src\session\session-manager-core.ts
@source-hash: b2962b7402a96b8b
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:51Z

## SessionManagerCore (L66–490)

Abstract base class providing core session lifecycle management, state transitions, and proxy event handling for debug sessions. Subclasses must implement `handleAutoContinue` and typically also provide DAP command dispatching.

### Architecture

- **Dependency injection**: All I/O, networking, logging, and factory dependencies are injected via `SessionManagerDependencies` (L44–52). No direct imports of concrete implementations.
- **SessionStore**: Instantiated via `sessionStoreFactory.create()` (L98); holds all `ManagedSession` objects.
- **Event handlers**: Named handler functions stored in a `WeakMap<ManagedSession, Map<string, handler>>` (L81) for clean removal. Prevents anonymous-handler leaks.
- **Dual state model**: Every state change updates both the legacy `SessionState` enum and the new `sessionLifecycle`/`executionState` fields via `mapLegacyState` (L137–141).

### Key Classes / Interfaces

- **`CustomLaunchRequestArguments` (L25–28)**: Extends `DebugProtocol.LaunchRequestArguments` with `stopOnEntry?` and `justMyCode?`.
- **`DebugResult` (L30–39)**: Result type returned from debug operations — contains `success`, `state`, optional `error`, `errorType` (machine-readable, e.g. `'PythonNotFoundError'`), `errorCode` (e.g. `-32602`), `data`, and `canContinue`.
- **`SessionManagerDependencies` (L44–52)**: DI bag: `fileSystem`, `networkManager`, `logger`, `proxyManagerFactory`, `sessionStoreFactory`, `environment`, `adapterRegistry`.
- **`SessionManagerConfig` (L57–61)**: Optional config: `logDirBase`, `defaultDapLaunchArgs`, `dryRunTimeoutMs`.
- **`SessionManagerCore` (L66–490)**: Abstract class; all fields `protected` except `adapterRegistry` (`public`).

### Key Methods

| Method | Lines | Description |
|---|---|---|
| `constructor` | L86–108 | Wires all DI, creates session store, ensures log dir exists |
| `createSession` | L110–119 | Creates a new session in the store and logs it |
| `findFreePort` | L121–123 | Delegates to `networkManager.findFreePort()` |
| `_getSessionById` | L125–127 | Retrieves session or throws; internal helper |
| `_updateSessionState` | L129–142 | Atomic state update: guards no-op, updates legacy + new lifecycle fields |
| `getSessionPolicy` | L147–150 | Returns `AdapterPolicy` for the session's language |
| `getSession` | L152–154 | Returns `ManagedSession | undefined` by ID |
| `getAllSessions` | L156–158 | Returns all `DebugSessionInfo[]` |
| `closeSession` | L160–198 | Cleans up handlers, stops proxy, marks STOPPED/TERMINATED, removes from store |
| `closeAllSessions` | L200–207 | Iterates all sessions and closes each |
| `setupProxyEventHandlers` | L209–444 | Registers named handlers for: `stopped`, `continued`, `terminated`, `exited`, `adapter-configured`, `dry-run-complete`, `error`, `exit` |
| `cleanupProxyEventHandlers` | L446–476 | Removes all registered handlers for a session; idempotent via WeakMap presence check |
| `_testOnly_cleanupProxyEventHandlers` | L481–483 | Public test-only wrapper for `cleanupProxyEventHandlers` |
| `handleAutoContinue` | L489 | **Abstract**; subclass must implement to issue DAP `continue` |

### setupProxyEventHandlers — Event Logic Details (L209–444)

- **`stopped`** (L237–292): Determines if the stop should auto-continue (launch-only, not attach, `stopOnEntry=false`, reason is `'entry'` or first-stop heuristic for adapters with `pauseAfterChildAttach`). Sets `PAUSED` state before calling `handleAutoContinue`. Sets `session.firstStopHandled = true`.
- **`continued`** (L297–319): Guards against stale continued events — if session is already `PAUSED`, the event is ignored.
- **`terminated` / `exited` / `error`** (L324–419): Each sets `STOPPED` or `ERROR`, cleans up handlers, nulls `session.proxyManager`, then calls `proxyManager.stop()` for process reaping (issue #122, Windows orphan prevention).
- **`adapter-configured`** (L377–385): Sets `RUNNING` state if `stopOnEntry` is false.
- **`dry-run-complete`** (L388–399): Sets `STOPPED`; only nulls `proxyManager` if `session._dryRunHandlerSetup` is not set (allows dry-run callers to observe result).
- **`exit`** (L422–439): Distinguishes clean exit (`code === 0` or `code === null && !signal` → `STOPPED`) from abnormal exit (→ `ERROR`).

### Important Invariants / Constraints

- `_updateSessionState` is a no-op if the new state equals the current state (L130).
- `setupProxyEventHandlers` resets `session.firstStopHandled = false` (L218) — safe for re-launched sessions.
- `cleanupProxyEventHandlers` uses WeakMap presence as a "already cleaned" guard (L448–451); safe to call multiple times.
- `adapterRegistry` is `public` (L75); all other fields are `protected`.
- Default `logDirBase`: `os.tmpdir()/debug-mcp-server/sessions` (L99).
- Default `dryRunTimeoutMs`: `10000` (L104).
- Default `defaultDapLaunchArgs`: `{ stopOnEntry: false, justMyCode: true }` (L100–103).

### Dependencies

- `@debugmcp/shared`: `SessionState`, `SessionLifecycleState`, `DebugLanguage`, `DebugSessionInfo`, `mapLegacyState`, `AdapterPolicy`, `IFileSystem`, `INetworkManager`, `ILogger`, `IEnvironment`, `IAdapterRegistry`
- `./session-store.js`: `SessionStore`, `ManagedSession`
- `@vscode/debugprotocol`: `DebugProtocol` (for `LaunchRequestArguments`)
- `../factories/session-store-factory.js`: `ISessionStoreFactory`
- `../proxy/proxy-manager.js`: `IProxyManager`
- `../factories/proxy-manager-factory.js`: `IProxyManagerFactory`
