# packages\adapter-dotnet\tests\unit\dotnet-debug-adapter.test.ts
@source-hash: f609baadf2f6fbbf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:47Z

## Unit Tests for `DotnetDebugAdapter`

Comprehensive vitest unit test suite for the `DotnetDebugAdapter` class, covering all public API surface areas including lifecycle, configuration, DAP protocol handling, and error translation.

### Test Structure

**Top-level suite:** `DotnetDebugAdapter` (L41–706), organized into 11 sub-suites:

1. **identity** (L52–60): Verifies `language === DebugLanguage.DOTNET` and `name` contains `.NET Debug Adapter`
2. **lifecycle** (L64–105): Initializes/disposes adapter; tests UNINITIALIZED → INITIALIZING → READY transitions, ERROR state on debugger not found, and dispose resetting state
3. **state management** (L109–139): Tests `isReady()`, `getCurrentThreadId()`, and `stateChanged` event emissions
4. **environment validation** (L143–170): Tests `validateEnvironment()` success/failure and `getRequiredDependencies()` (expects 2 deps, first is `netcoredbg` required)
5. **executable management** (L174–200): Tests `resolveExecutablePath()`, 60-second caching (only 1 call on double-invoke), `getDefaultExecutableName()`, `getExecutableSearchPaths()`
6. **adapter configuration** (L204–250): Tests `buildAdapterCommand()` — bridge pattern using `process.execPath`, args[0] is `netcoredbg-bridge`, args[1] is executable path, args[2] is port string; `getAdapterModuleName()`, `getAdapterInstallCommand()`
7. **launch configuration** (L254–288): Tests `transformLaunchConfig()` → `{type: 'coreclr', request: 'launch'}`, defaults `stopOnEntry: true`, `justMyCode: true`; `getDefaultLaunchConfig()`
8. **attach configuration** (L292–468): Most comprehensive suite — attach/detach support, `transformAttachConfig()` with coreclr type, `terminateDebuggee: false` (CRITICAL), string→number processId coercion, `sourceFileMap` construction from `sourcePaths`, PDB conversion via `pdb2pdb`, auto-detection of process executable dir, architecture detection/propagation to `resolveExecutablePath()`, `getDefaultAttachConfig()`
9. **connection management** (L472–505): Tests `connect()`/`disconnect()` state transitions, `connected` event, thread ID cleared on disconnect
10. **DAP event handling** (L509–541): Tests `handleDapEvent()` for `stopped` event updating thread ID, graceful handling of events without `threadId`, `handleDapResponse()` no-throw
11. **DAP request validation** (L545–567): Tests `sendDapRequest('setExceptionBreakpoints')` rejects invalid filters with `'Invalid .NET exception filters'`, accepts `['all', 'user-unhandled']`, passes through non-exception requests
12. **feature support** (L571–603): Tests `supportsFeature()` for CONDITIONAL_BREAKPOINTS, FUNCTION_BREAKPOINTS, EXCEPTION_BREAKPOINTS, SET_VARIABLE, EVALUATE_FOR_HOVERS (all true); STEP_BACK, LOG_POINTS, DATA_BREAKPOINTS (all false)
13. **capabilities** (L607–638): Tests `getCapabilities()` object fields; CRITICAL: `supportTerminateDebuggee === false`; exception breakpoint filters has 2 entries (`all`, `user-unhandled`), with `user-unhandled` as default
14. **error handling** (L642–684): Tests `getInstallationInstructions()`, `getMissingExecutableError()`, `translateErrorMessage()` for 5 patterns (netcoredbg not found → NETCOREDBG_PATH, attach denied → Administrator, process not found → PID, PDB symbols → Portable PDB, connection refused → netcoredbg)
15. **feature requirements** (L688–705): Tests `getFeatureRequirements()` for CONDITIONAL_BREAKPOINTS (dep type), EXCEPTION_INFO_REQUEST (PDB description), SET_VARIABLE (empty array)

### Mock Setup

**`dotnet-utils.js` module mocked entirely** (L11–19) via `vi.mock()`. Typed mock references (L21–25):
- `findNetcoredbgExecutableMock` — most used; controls executable path resolution and error cases
- `findPdb2PdbExecutableMock` — controls PDB conversion tool availability (synchronous mock)
- `convertPdbsToTempMock` — controls PDB conversion result path (synchronous mock)
- `getProcessExecutableDirMock` — controls process executable directory auto-detection
- `getProcessArchitectureMock` — controls detected process architecture (e.g., `'x86'`)

**`createDependencies()` factory** (L27–39): Creates minimal `AdapterDependencies` stub with no-op fileSystem, environment (returns `undefined`/`{}`/`process.cwd()`), and logger.

**`beforeEach`** (L44–48): Clears all mocks, resets `findNetcoredbgExecutableMock`, creates fresh adapter instance.

### Key Invariants Tested

- Adapter command uses bridge pattern: node → bridge script → netcoredbg path → port (L218–224)
- `terminateDebuggee` is always `false` in attach config (L316–323) — safety-critical
- `supportTerminateDebuggee` capability is `false` (L620–623) — safety-critical  
- `type: 'coreclr'` is injected into both launch and attach configs
- PDB conversion skipped when `pdb2pdb` returns null OR `convertPdbsToTemp` returns null
- Architecture detection only occurs when `processId` is present (L453–461)
- Executable path is cached — second `resolveExecutablePath()` call uses cache (L183–189)
- `dispose()` resets to UNINITIALIZED, clears connection and thread state

### Dependencies

- `DotnetDebugAdapter` from `../../src/DotnetDebugAdapter.js`
- `dotnet-utils.js` utilities (mocked): `findNetcoredbgExecutable`, `findPdb2PdbExecutable`, `convertPdbsToTemp`, `getProcessExecutableDir`, `getProcessArchitecture`
- `@debugmcp/shared`: `DebugLanguage`, `AdapterState`, `DebugFeature`, `AdapterDependencies`