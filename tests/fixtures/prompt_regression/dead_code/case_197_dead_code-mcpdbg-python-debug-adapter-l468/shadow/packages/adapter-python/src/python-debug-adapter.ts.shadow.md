# packages\adapter-python\src\python-debug-adapter.ts
@source-hash: 24a6cb88add44548
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:24Z

## PythonDebugAdapter — Python-specific DAP adapter implementation

### Purpose
Implements `IDebugAdapter` for Python debugging via debugpy. Handles Python executable discovery, environment validation (version + debugpy presence), DAP config transformation, and state lifecycle management. Actual DAP communication is delegated to `ProxyManager`; this adapter handles Python-specific logic only.

### Primary Export
**`PythonDebugAdapter`** (L81–773): `EventEmitter` + `IDebugAdapter`. Core adapter class.

---

### Key Fields
| Field | Type | Description |
|---|---|---|
| `language` | `DebugLanguage.PYTHON` | Readonly discriminant |
| `state` | `AdapterState` | Internal lifecycle state |
| `pythonPathCache` | `Map<string, PythonPathCacheEntry>` | 1-minute TTL cache for resolved Python paths, versions, and debugpy presence |
| `cacheTimeout` | `60000` | Cache TTL in ms |
| `currentThreadId` | `number \| null` | Tracks current stopped thread from DAP events |
| `connected` | `boolean` | True after `connect()` call |

---

### Lifecycle Methods
- **`initialize()`** (L103–132): Calls `validateEnvironment()`, transitions to `READY` or `ERROR`. Emits `'initialized'`. CI-environment logging is present.
- **`dispose()`** (L134–140): Clears cache, resets state to `UNINITIALIZED`, emits `'disposed'`.
- **`transitionTo(newState)`** (L158–162): Private; emits `'stateChanged'` with old/new state.

---

### Environment Validation
- **`validateEnvironment(executablePath?)`** (L166–243): Validates Python ≥3.7 and debugpy installation. When `executablePath` is provided and debugpy is missing → error; when auto-detected and debugpy missing → warning (virtualenv-friendly). Returns `ValidationResult`.
- **`checkPythonVersion(pythonPath)`** (L704–719): Private. Uses `getPythonVersion()` utility; caches result under explicit `pythonPath` key.
- **`checkDebugpyInstalled(pythonPath)`** (L724–753): Private. Spawns `python -c 'import debugpy; print(debugpy.__version__)'`; caches `hasDebugpy` boolean.
- **`detectVirtualEnv(pythonPath)`** (L758–772): Private. Spawns Python to check `sys.real_prefix` / `sys.base_prefix != sys.prefix`.

---

### Executable Resolution
- **`resolveExecutablePath(preferredPath?)`** (L264–287): Checks cache, delegates to `findPythonExecutable()`. Cache key: `preferredPath || 'default'`.
- **`getDefaultExecutableName()`** (L289–296): Returns `'py'` on win32, `'python3'` otherwise.
- **`getExecutableSearchPaths()`** (L298–346): Returns platform-specific search paths plus `PATH` entries.

---

### Adapter Command / Config
- **`buildAdapterCommand(config)`** (L350–364): Builds command: `python -m debugpy.adapter --host <host> --port <port>` with `PYTHONUNBUFFERED=1` and `DEBUGPY_LOG_DIR`.
- **`transformLaunchConfig(config)`** (L376–390): Adds `type: 'python'`, `request: 'launch'`, `console: 'internalConsole'`, `redirectOutput: true`, `justMyCode`, `stopOnEntry`.
- **`transformAttachConfig(config)`** (L413–456): Produces `PythonAttachConfig` with `connect: { host, port }`. Rejects process-ID/name attach (not supported by debugpy). Throws `AdapterError` if `port` is not a number.
- **`getDefaultLaunchConfig()`** (L392–399): Returns `{ stopOnEntry: false, justMyCode: true, env: {}, cwd: process.cwd() }`.
- **`getDefaultAttachConfig()`** (L458–464): Returns `{ request: 'attach', host: '127.0.0.1', justMyCode: true }`.

---

### DAP Protocol Handling
- **`sendDapRequest(command, args?)`** (L468–491): Validates `setExceptionBreakpoints` filters against `['raised', 'uncaught', 'userUnhandled']`; returns empty object `{}` — actual communication done by `ProxyManager`.
- **`handleDapEvent(event)`** (L493–501): Updates `currentThreadId` on `'stopped'` events; re-emits event on the EventEmitter.
- **`handleDapResponse(_response)`** (L503–505): No-op; Python adapter needs no special response handling.

---

### Connection Management
- **`connect(host, port)`** (L509–517): Sets `connected = true`, transitions to `CONNECTED`, emits `'connected'`. Actual TCP connection handled by `ProxyManager`.
- **`disconnect()`** (L519–524): Resets `connected` and `currentThreadId`, transitions to `DISCONNECTED`.

---

### Capabilities (L635–697)
Full `AdapterCapabilities` object. Highlights:
- Supports: conditional/function/exception/log-point breakpoints, `setVariable`, step-in targets, completions (triggers: `.`, `[`), modules, exception options/info, loaded sources, breakpoint locations, exception filter options.
- Does NOT support: step back, restart frame, goto targets, restart, data breakpoints, memory R/W, disassemble, cancel, clipboard context, stepping granularity, instruction breakpoints, single-thread execution.

---

### Feature Support
- **`supportsFeature(feature)`** (L586–601): Checks against hardcoded set of 10 `DebugFeature` values.
- **`getFeatureRequirements(feature)`** (L603–633): Returns version/dependency requirements for `CONDITIONAL_BREAKPOINTS` (debugpy 1.0+), `LOG_POINTS` (debugpy 1.5+), `EXCEPTION_INFO_REQUEST` (Python 3.7+).

---

### Error Handling / User-Facing Text
- **`translateErrorMessage(error)`** (L562–582): Maps lowercased error messages to user-friendly strings for: debugpy not found, Python not found, permission denied, Windows Store alias.
- **`getInstallationInstructions()`** / **`getMissingExecutableError()`**: Return multi-line instructional strings.

---

### Internal Interfaces
- **`PythonPathCacheEntry`** (L42–47): `{ path, timestamp, version?, hasDebugpy? }`
- **`PythonLaunchConfig`** (L52–63): Extends `LanguageSpecificLaunchConfig` with `module`, `pythonArgs`, `console`, `django`, `flask`, `jinja`, `redirectOutput`, `showReturnValue`, `subProcess`.
- **`PythonAttachConfig`** (L68–76): `type: 'python'`, `request: 'attach'`, `connect: { host, port }`, `justMyCode`, optional `cwd`/`env`.

---

### Dependencies
- `AdapterDependencies` injected via constructor; provides `logger` (optional, used for debug/info logging).
- `findPythonExecutable`, `getPythonVersion` from `./utils/python-utils.js`.
- `sanitizeStderrTail` from `@debugmcp/shared` — used to sanitize debugpy version output before logging.
- `spawn` from `child_process` — used directly for `checkDebugpyInstalled` and `detectVirtualEnv`.

---

### Architectural Notes
- Cache key strategy: `preferredPath || 'default'` for path cache; version/debugpy checks store under explicit `pythonPath` key with fallback read from `'default'` key to avoid miss after resolution.
- `sendDapRequest` is a stub returning `{}` — real DAP round-trips are in `ProxyManager`.
- `connect()` is also a state-marker; no TCP work happens here.
- CI-mode diagnostic logging via `process.env.CI === 'true'` guard throughout `initialize()` and `validateEnvironment()`.