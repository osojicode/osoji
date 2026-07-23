# packages\adapter-dotnet\tests\unit\dotnet-debug-adapter.test.ts
@source-hash: f609baadf2f6fbbf
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:00Z

## Unit Tests: DotnetDebugAdapter

Comprehensive unit test suite for `DotnetDebugAdapter`, covering identity, lifecycle, state management, environment validation, executable resolution, adapter configuration, launch/attach config transformation, DAP event/request handling, feature support, capabilities, error handling, and feature requirements.

### Test Setup (L1–48)
- **Mocks**: All functions from `../../src/utils/dotnet-utils.js` are mocked via `vi.mock` (L11–19): `findNetcoredbgExecutable`, `findDotnetBackend`, `listDotnetProcesses`, `findPdb2PdbExecutable`, `convertPdbsToTemp`, `getProcessExecutableDir`, `getProcessArchitecture`.
- **Typed mock references** (L21–25): `findNetcoredbgExecutableMock`, `findPdb2PdbExecutableMock`, `convertPdbsToTempMock`, `getProcessExecutableDirMock`, `getProcessArchitectureMock`.
- **`createDependencies()`** (L27–39): Factory returning a minimal `AdapterDependencies` stub with no-op `fileSystem`, `environment` (returns `undefined`/`{}`/`cwd()`), and `logger`.
- **`beforeEach`** (L44–48): Clears all mocks, resets `findNetcoredbgExecutableMock`, creates a fresh `DotnetDebugAdapter` instance.

### Test Groups

#### Identity (L52–60)
- `adapter.language` === `DebugLanguage.DOTNET`
- `adapter.name` contains `'.NET Debug Adapter'`

#### Lifecycle (L64–105)
- Initial state: `AdapterState.UNINITIALIZED`
- Successful `initialize()` → `AdapterState.READY`, `isReady() === true`, emits `'initialized'` event
- Failed `initialize()` (mock rejects) → throws, state becomes `AdapterState.ERROR`
- `dispose()` → state resets to `UNINITIALIZED`, `isConnected() === false`, `getCurrentThreadId() === null`

#### State Management (L109–139)
- `isReady()` is `true` for READY and CONNECTED states
- `isReady()` is `false` for UNINITIALIZED
- `getCurrentThreadId()` is `null` initially
- `stateChanged` event emits `[UNINITIALIZED→INITIALIZING, INITIALIZING→READY]` transitions during `initialize()`

#### Environment Validation (L143–170)
- `validateEnvironment()` returns `{ valid: true, errors: [] }` when `findNetcoredbgExecutable` resolves
- Returns `{ valid: false, errors: [{ code: 'DEBUGGER_NOT_FOUND' }] }` when it rejects
- `getRequiredDependencies()` returns 2 items; first is `{ name: 'netcoredbg', required: true }`

#### Executable Management (L174–200)
- `resolveExecutablePath()` delegates to `findNetcoredbgExecutable`, returns its resolved value
- **Path caching**: Second call within 60s does NOT call the mock again (called only once)
- `getDefaultExecutableName()` → `'netcoredbg'`
- `getExecutableSearchPaths()` → non-empty array

#### Adapter Configuration (L204–250)
- `buildAdapterCommand()` returns `{ command: process.execPath, args: [<bridge-path-containing 'netcoredbg-bridge'>, executablePath, port-string], env: object }`
- `getAdapterModuleName()` → `'netcoredbg'`
- `getAdapterInstallCommand()` contains `'netcoredbg'`

#### Launch Configuration (L254–288)
- `transformLaunchConfig({ stopOnEntry, justMyCode, cwd })` → `{ type: 'coreclr', request: 'launch', justMyCode, stopOnEntry }`
- Defaults: `stopOnEntry: true`, `justMyCode: true`
- `getDefaultLaunchConfig()` → `{ stopOnEntry: true, justMyCode: true }`

#### Attach Configuration (L292–468)
- `supportsAttach()` → `true`; `supportsDetach()` → `true`
- `transformAttachConfig()` produces `{ type: 'coreclr', request: 'attach', processId, justMyCode }`
- **CRITICAL**: Always sets `terminateDebuggee: false`
- Converts string `processId` to number (L325–332)
- Builds `sourceFileMap` from `sourcePaths` array (L334–345)
- PDB conversion (L347–407):
  - When `sourcePaths` + `findPdb2PdbExecutable` available: calls `convertPdbsToTemp(sourcePaths, pdb2pdbPath)`, sets `symbolOptions.searchPaths`
  - Skips when `findPdb2PdbExecutable` returns `null`
  - Skips when `convertPdbsToTemp` returns `null`
  - Auto-detects process executable dir via `getProcessExecutableDir(processId)` when no `sourcePaths`
  - Skips auto-detection when `sourcePaths` provided
- Architecture detection (L424–461):
  - Calls `getProcessArchitecture(processId)` during `transformAttachConfig`
  - Detected architecture (e.g., `'x86'`) is passed to `findNetcoredbgExecutable` as 3rd arg
  - Skips when no `processId`
- `getDefaultAttachConfig()` → `{ justMyCode: true }`

#### Connection Management (L472–505)
- `connect(host, port)` → `isConnected() === true`, state `CONNECTED`, emits `'connected'`
- `disconnect()` → `isConnected() === false`, state `DISCONNECTED`, clears thread ID
- Thread ID set by `handleDapEvent({ event: 'stopped', body: { threadId: 42 } })`, cleared on disconnect

#### DAP Event Handling (L509–541)
- `handleDapEvent` with `'stopped'` + `threadId` → updates `getCurrentThreadId()`
- `handleDapEvent` with events lacking `threadId` (e.g., `'output'`) → does not crash, thread stays `null`
- `handleDapResponse` does not throw

#### DAP Request Validation (L545–567)
- `sendDapRequest('setExceptionBreakpoints', { filters: ['invalid-filter'] })` → rejects with `'Invalid .NET exception filters'`
- Valid filters `['all', 'user-unhandled']` → resolves
- Other commands (e.g., `'continue'`) → resolves

#### Feature Support (L571–603)
- Supported: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `SET_VARIABLE`, `EVALUATE_FOR_HOVERS`
- Not supported: `STEP_BACK`, `LOG_POINTS`, `DATA_BREAKPOINTS`

#### Capabilities (L607–638)
- `getCapabilities()` has: `supportsConfigurationDoneRequest`, `supportsConditionalBreakpoints`, `supportsFunctionBreakpoints`, `supportsSetVariable`, `supportsEvaluateForHovers`, `supportsModulesRequest`, `supportsLoadedSourcesRequest` all `true`
- **CRITICAL**: `supportTerminateDebuggee === false`
- `supportsStepBack === false`
- `exceptionBreakpointFilters` has 2 entries: `'all'` and `'user-unhandled'` (latter is default)

#### Error Handling (L642–684)
- `getInstallationInstructions()` contains `'netcoredbg'`
- `getMissingExecutableError()` contains `'netcoredbg not found'`
- `translateErrorMessage` pattern matching:
  - `'netcoredbg not found'` → mentions `'NETCOREDBG_PATH'`
  - `'attach denied'` → mentions `'Administrator'`
  - `'target process not found'` → mentions `'PID'`
  - `'symbol load PDB'` → mentions `'Portable PDB'`
  - `'connection refused'` → mentions `'netcoredbg'`
  - Unrecognized → passes through verbatim

#### Feature Requirements (L688–705)
- `getFeatureRequirements(CONDITIONAL_BREAKPOINTS)` → non-empty, first item `{ type: 'dependency' }`
- `getFeatureRequirements(EXCEPTION_INFO_REQUEST)` → non-empty, first `description` contains `'PDB'`
- `getFeatureRequirements(SET_VARIABLE)` → empty array

### Key Invariants Tested
- `terminateDebuggee` is always `false` in attach config (safety invariant)
- `supportTerminateDebuggee` capability is always `false`
- Executable path is cached after first resolution
- Architecture hint from `transformAttachConfig` propagates to `resolveExecutablePath`
