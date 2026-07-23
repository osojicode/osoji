# tests\unit\adapter-python\python-debug-adapter.test.ts
@source-hash: b77d583654579d40
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:44Z

## Unit Tests: PythonDebugAdapter

Test suite for `PythonDebugAdapter` from `packages/adapter-python`. Covers initialization lifecycle, environment validation, DAP request/event handling, launch/attach configuration transformation, feature support, and error translation.

### Module-Level Setup (L6–17)
- Mocks `child_process` (`spawn`, `exec`) and `python-utils` (`findPythonExecutable`, `getPythonVersion`) via `vi.mock`
- Uses top-level `await import(...)` to capture typed mock references after `vi.mock` hoisting

### `createDependencies` factory (L19–29)
Returns a minimal dependency object with stub `fileSystem`, `environment`, stub `logger` (all methods are `vi.fn()`), and `networkManager: undefined`. Used in every test.

### Test Cases

**Caching (L36–46)**
- `resolveExecutablePath` caches results; `findPythonExecutable` called only once on repeat calls.

**`validateEnvironment` (L48–87)**
- Python version `3.6.9` → `valid: false`, error code `PYTHON_VERSION_TOO_OLD` (L48–59)
- debugpy missing + virtual env detected → `valid: true`, `DEBUGPY_NOT_INSTALLED` in warnings (not errors); logs virtual env detection (L61–77, issue #106)
- `resolveExecutablePath` rejection → `valid: false`, error code `PYTHON_NOT_FOUND` (L79–87)

**Version cache (L89–98)**
- Directly seeds `pythonPathCache` map with a version; `checkPythonVersion` returns cached value without calling `getPythonVersion`.

**`buildAdapterCommand` (L100–115)**
- Returns `command: executablePath`, `args: ['-m', 'debugpy.adapter', '--host', host, '--port', port]`, `env.DEBUGPY_LOG_DIR` set to `logDir`.

**`sendDapRequest` (L117–131)**
- `setExceptionBreakpoints` with invalid filter → rejects with `AdapterError`
- `setExceptionBreakpoints` with `['raised', 'uncaught']` → resolves to `{}`

**`handleDapEvent` (L133–143)**
- `stopped` event with `body.threadId: 42` → `getCurrentThreadId()` returns `42`

**Feature support (L145–153)**
- `LOG_POINTS` supported, `DISASSEMBLE_REQUEST` not supported
- `getFeatureRequirements(EXCEPTION_INFO_REQUEST)` includes entry with `'Python 3.7+'`

**`translateErrorMessage` (L155–168)**
- `ModuleNotFoundError: No module named debugpy` → message contains `'debugpy'`
- `python: command not found` → `'Python not found'`
- `Permission denied` → `'Permission denied'`
- `Windows Store Python` → `'Windows Store'`
- Unknown error → original message passthrough

**`getFeatureRequirements` (L170–180)**
- `LOG_POINTS` → `[{ description: 'debugpy 1.5+', required: true }]`
- `VARIABLE_PAGING` → `[]`

**`initialize` lifecycle (L182–208)**
- Success: `validateEnvironment` returns `valid: true` → state becomes `AdapterState.READY`, `'initialized'` event emitted
- Failure: `validateEnvironment` returns `valid: false` → rejects with `AdapterError`, state becomes `AdapterState.ERROR`

**Connect/disconnect (L210–226)**
- `connect('localhost', 5678)` → state `CONNECTED`, `isConnected() === true`, `'connected'` event
- `disconnect()` → state `DISCONNECTED`, `isConnected() === false`, `'disconnected'` event

**`checkDebugpyInstalled` (L228–262)**
- Success path: spawns Python with `-c 'import debugpy; print(debugpy.__version__)'`, stdout emits version, exit 0 → resolves `true`
- Error path: child emits `'error'` → resolves `false`

**`transformLaunchConfig` (L264–280)**
- Merges caller config over defaults; sets `name: 'Python: Current File'`, `console: 'internalConsole'`, `redirectOutput: true`, `showReturnValue: true`; caller `stopOnEntry: true` / `justMyCode: false` preserved

**`dispose` (L282–294)**
- After connect/disconnect, `dispose()` emits `'disposed'`, state → `UNINITIALIZED`, `isConnected() === false`

**`getCapabilities` (L296–307)**
- `supportsConfigurationDoneRequest: true`
- `exceptionBreakpointFilters` contains objects with `filter: 'raised'` and `filter: 'uncaught'`

**Installation/help strings (L309–314)**
- `getInstallationInstructions()` contains `'pip install debugpy'`
- `getMissingExecutableError()` contains `'Python not found'`

**`getDefaultLaunchConfig` (L316–324)**
- `stopOnEntry: false`, `justMyCode: true`, `env: {}`, `cwd: process.cwd()`

### Attach Support Tests (L326–400, issue #145)

**Attach capabilities (L327–333)**
- `supportsAttach()`, `supportsDetach()`, `usesDirectConnectForAttach()` all return `true`

**`transformAttachConfig` (L335–364)**
- Full config: `request: 'attach'`, produces `connect: { host, port }`, strips top-level `host`/`port` (mutually exclusive in debugpy), strips `__attachMode` and launch-template fields like `console`

**Defaults (L366–375)**
- No host → defaults to `'127.0.0.1'`; no `justMyCode` → defaults to `true`

**Validation errors (L377–389)**
- Missing `port` → throws with `/port/i`
- `processId` provided → throws with `/process id/i` (PID attach not supported, use debugpy `--listen`)

**`getDefaultAttachConfig` (L391–399)**
- Returns `{ request: 'attach', host: '127.0.0.1', justMyCode: true }`

### Architecture Notes
- All private methods (`checkPythonVersion`, `checkDebugpyInstalled`, `detectVirtualEnv`) accessed via `(adapter as any)` cast for unit-level isolation
- `pythonPathCache` internal `Map` directly seeded for cache-hit tests
- `child_process.spawn` mock returns a manually constructed `EventEmitter` tree to simulate async subprocess I/O
