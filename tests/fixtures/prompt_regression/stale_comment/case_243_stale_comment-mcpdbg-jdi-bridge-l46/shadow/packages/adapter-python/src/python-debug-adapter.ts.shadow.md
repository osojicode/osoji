# packages\adapter-python\src\python-debug-adapter.ts
@source-hash: 24a6cb88add44548
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:44Z

## PythonDebugAdapter

Primary implementation of `IDebugAdapter` for Python debugging via debugpy. Manages Python executable discovery/caching, environment validation, DAP configuration transformation, and adapter lifecycle. Extends `EventEmitter` and emits `initialized`, `disposed`, `stateChanged`, `connected`, `disconnected`, and forwarded DAP events.

### Key Classes

**`PythonDebugAdapter`** (L81–773) — Central class implementing `IDebugAdapter`. Stateful: tracks `AdapterState` (UNINITIALIZED → INITIALIZING → READY → CONNECTED/DEBUGGING → DISCONNECTED/ERROR), current thread ID, and connection status.

### Private Interfaces

- **`PythonPathCacheEntry`** (L42–47): Cache shape for Python path lookup — stores `path`, `timestamp`, optional `version` and `hasDebugpy`.
- **`PythonLaunchConfig`** (L52–63): Extends `LanguageSpecificLaunchConfig` with Python-specific fields (`module`, `pythonArgs`, `django`, `flask`, `jinja`, `redirectOutput`, `showReturnValue`, `subProcess`, `console`).
- **`PythonAttachConfig`** (L68–76): Extends `LanguageSpecificAttachConfig` with debugpy client-connect shape — critically uses `connect: { host, port }` (NOT top-level `host`/`port`) to comply with debugpy's mutual exclusion rule.

### Key Methods

| Method | Lines | Purpose |
|---|---|---|
| `constructor` | L96–99 | Stores injected `AdapterDependencies` |
| `initialize()` | L103–132 | Validates environment, transitions state to READY or ERROR, emits `initialized` |
| `dispose()` | L134–140 | Clears cache, resets state, emits `disposed` |
| `getState()` | L144–146 | Returns current `AdapterState` |
| `isReady()` | L148–152 | True if READY, CONNECTED, or DEBUGGING |
| `getCurrentThreadId()` | L154–156 | Returns last stopped thread ID |
| `transitionTo()` | L158–162 | Private state machine — emits `stateChanged(oldState, newState)` |
| `validateEnvironment()` | L166–243 | Checks Python version (≥3.7), debugpy availability, virtualenv. Missing `executablePath` → warning (not error) for debugpy absence |
| `getRequiredDependencies()` | L245–260 | Returns `[Python 3.7+, debugpy]` |
| `resolveExecutablePath()` | L264–287 | Cached Python path lookup (60s TTL), delegates to `findPythonExecutable` |
| `getDefaultExecutableName()` | L289–296 | `py` on win32, `python3` otherwise |
| `getExecutableSearchPaths()` | L298–346 | Returns platform-specific Python install dirs + PATH entries |
| `buildAdapterCommand()` | L350–364 | Constructs `python -m debugpy.adapter --host H --port P` with `PYTHONUNBUFFERED=1` and `DEBUGPY_LOG_DIR` |
| `transformLaunchConfig()` | L376–390 | Merges generic config into Python-typed launch config with defaults (`internalConsole`, `redirectOutput: true`, `justMyCode: true`) |
| `getDefaultLaunchConfig()` | L392–399 | `stopOnEntry: false, justMyCode: true, env: {}, cwd: process.cwd()` |
| `supportsAttach()` | L401–403 | Always `true` |
| `supportsDetach()` | L405–407 | Always `true` |
| `usesDirectConnectForAttach()` | L409–411 | Always `true` — bypasses adapter spawn for attach |
| `transformAttachConfig()` | L413–456 | Validates port presence; rejects process-ID attach; builds `PythonAttachConfig` with `connect:{ host, port }` |
| `getDefaultAttachConfig()` | L458–464 | `host: 127.0.0.1, justMyCode: true` |
| `sendDapRequest()` | L468–491 | Validates Python exception filter names (`raised`, `uncaught`, `userUnhandled`); returns empty stub (actual comms in ProxyManager) |
| `handleDapEvent()` | L493–501 | Extracts `threadId` from `stopped` events; re-emits all DAP events |
| `handleDapResponse()` | L503–505 | No-op |
| `connect()` | L509–517 | Marks connected, transitions to CONNECTED, emits `connected` |
| `disconnect()` | L519–524 | Marks disconnected, clears threadId, transitions to DISCONNECTED |
| `isConnected()` | L526–528 | Returns `this.connected` |
| `getInstallationInstructions()` | L532–550 | User-facing setup guide string |
| `getMissingExecutableError()` | L552–560 | User-facing error string for missing Python |
| `translateErrorMessage()` | L562–582 | Maps known error messages to friendly text |
| `supportsFeature()` | L586–601 | Checks against hardcoded supported `DebugFeature` set |
| `getFeatureRequirements()` | L603–633 | Returns version/dependency requirements per feature |
| `getCapabilities()` | L635–697 | Full `AdapterCapabilities` object for DAP capability negotiation |
| `checkPythonVersion()` | L704–719 | Private — spawns `getPythonVersion`, caches result under `pythonPath` key |
| `checkDebugpyInstalled()` | L724–753 | Private — spawns `python -c 'import debugpy'`, caches `hasDebugpy` under `pythonPath` key |
| `detectVirtualEnv()` | L758–772 | Private — spawns python to check `sys.real_prefix`/`sys.base_prefix` |

### Caching Strategy
- `pythonPathCache: Map<string, PythonPathCacheEntry>` keyed by `preferredPath ?? 'default'`
- Cache TTL: 60,000ms (L90)
- `checkPythonVersion` and `checkDebugpyInstalled` check both `pythonPath` key AND `'default'` key as fallback (L706, L726), then store under `pythonPath` key to avoid key mismatch
- `resolveExecutablePath` stores under `preferredPath ?? 'default'`

### Attach Flow — Important Constraint
`PythonAttachConfig` uses `connect: { host, port }` exclusively (L439). debugpy rejects configurations that have both top-level `host`/`port` AND `connect.*` simultaneously. The `usesDirectConnectForAttach()` returning `true` signals the factory/manager layer to skip adapter-process spawning.

### Environment Validation Logic
- Explicit `executablePath` → debugpy absence is an **error** (L207–210)
- Auto-detected Python → debugpy absence is a **warning** (L213–218) — virtualenv users may have debugpy in their venv

### Dependencies
- `AdapterDependencies` (injected): provides optional `logger` (used throughout for debug/info logging)
- `findPythonExecutable`, `getPythonVersion` from `./utils/python-utils.js`
- `sanitizeStderrTail` from `@debugmcp/shared` — used to clean debugpy version output before logging

### Events Emitted
`initialized`, `disposed`, `stateChanged`, `connected`, `disconnected`, plus forwarded DAP event names from `handleDapEvent`

### Architecture Notes
- Actual DAP communication is delegated to `ProxyManager` — `sendDapRequest` returns a stub `{} as T`
- CI-mode logging: scattered `process.env.CI === 'true'` guards throughout `initialize` and `validateEnvironment` for debugging in CI pipelines
- `buildAdapterCommand` spreads `process.env` into the child process env, which may leak sensitive environment variables
