# tests\adapters\java\unit\java-debug-adapter.test.ts
@source-hash: 79deee40c46513be
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:01Z

## Overview
Unit test suite for `JavaDebugAdapter` from `@debugmcp/adapter-java`. Tests cover the full lifecycle of the adapter: initialization (Java version detection via spawned process), state transitions, DAP event handling, capability querying, error translation, launch/attach config transformation, and command building. Uses Vitest with `child_process.spawn` mocked via `vi.mock`.

## Test Setup (L1-63)
- **`vi.mock('child_process')`** (L9-15): Replaces `spawn` with a `vi.fn()` while preserving all other exports via `importOriginal`.
- **`mockSpawn`** (L17): Typed reference to the mocked `spawn` via `vi.mocked`.
- **`createMockDependencies()`** (L19-48): Factory returning a full `AdapterDependencies` stub. `fileSystem` methods return empty/false defaults. `logger` uses `vi.fn()` spies. `environment.get` delegates to `process.env`.
- **`beforeEach`**: Clears all mocks, recreates `mockDependencies` and `adapter = new JavaDebugAdapter(mockDependencies)`.
- **`afterEach`**: Calls `vi.clearAllMocks()` and `vi.unstubAllGlobals()`.

## Test Groups

### `basic properties` (L65-81)
- `adapter.language` → `DebugLanguage.JAVA`
- `adapter.name` → `'Java Debug Adapter (JDI)'`
- Initial state → `AdapterState.UNINITIALIZED`; `isReady()` → `false`

### `initialize` (L83-158)
Mocks `spawn` to emit version output on `stderr` then `exit 0`. Key cases:
- Java 17 → state `READY`, `isReady()` true, emits `'initialized'` event (L84-120)
- `spawn` emitting `'error'` → rejects, state `ERROR` (L122-136)
- Java 8 (`"1.8.0_292"`) → state still `READY` but `logger.warn` called with string containing `'Java 11+ recommended'` (L138-157)

### `dispose` (L160-187)
- After `initialize()`, `dispose()` resets state to `UNINITIALIZED`
- `dispose()` emits `'disposed'` event (even without prior initialize)

### `connect/disconnect` (L189-219)
- `connect('127.0.0.1', 38000)` → state `CONNECTED`, `isConnected()` true, emits `'connected'`
- `disconnect()` → state `DISCONNECTED`, `isConnected()` false, emits `'disconnected'`

### `getRequiredDependencies` (L221-228)
- Returns array of length 1; `[0].name === 'JDK'`; `[0].required === true`

### `supportsFeature` (L230-258)
Supported: `CONDITIONAL_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `TERMINATE_REQUEST`
Not supported: `FUNCTION_BREAKPOINTS`, `STEP_BACK`, `DATA_BREAKPOINTS`

### `getCapabilities` (L260-282)
- Verifies individual boolean capability flags
- `exceptionBreakpointFilters` has length 2; filters are `'caught'` and `'uncaught'`

### `translateErrorMessage` (L284-321)
- `'JDI bridge not compiled'` → contains `'JDI bridge not compiled'` and `'build:adapter'`
- `'java: command not found'` → contains `'Java not found'`
- `'permission denied'` → contains `'Permission denied'`
- `'java.lang.ClassNotFoundException'` → contains `'class not found'`
- `'java.lang.NoClassDefFoundError'` → contains `'class not found'`
- Unknown errors pass through unchanged

### `getInstallationInstructions` (L323-330)
- Result contains `'JDK'`, `'adoptium'`, `'build:adapter'`

### `getMissingExecutableError` (L332-338)
- Contains `'Java not found'` and `'adoptium'`

### `buildAdapterCommand` (L340-421)
- **Environment-conditional**: Tests use try/catch because JDI bridge JAR may not exist in CI. If compiled: verifies `result.command` truthy, `result.args` contains `'JdiDapServer'`. If not: verifies error matches `/JDI bridge not compiled/`.
- Port 0 → throws matching `/JDI bridge not compiled|Valid TCP port/`
- `MCP_DEBUGGER_MAIN_PID` env set → `--owner-pid` arg equals that value (L380-400)
- `MCP_DEBUGGER_MAIN_PID` unset → `--owner-pid` falls back to `String(process.ppid)` (L402-421)

### `transformLaunchConfig` (L424-488)
- Returns `type: 'java'`, `request: 'launch'`
- `.java` file path → `mainClass` is basename without extension (e.g., `'Main'`)
- Dotted class name passthrough (`'com.example.Main'`)
- `stopOnEntry` defaults to `true`; can be overridden to `false`
- `classpath` and `sourcePath` fields passed through unchanged

### `handleDapEvent` (L490-578, L709-725)
State transitions: `'stopped'` → `DEBUGGING` + updates `getCurrentThreadId()`; `'continued'` → `DEBUGGING`; `'terminated'` → `DISCONNECTED`
Events forwarded: `'exited'`, `'thread'`, `'output'`, `'breakpoint'`

### `sendDapRequest` (L580-585)
- Always rejects with `'DAP request forwarding not implemented'`

### `handleDapResponse` (L587-599)
- No-op; must not throw

### `getDefaultLaunchConfig` (L601-607)
- `stopOnEntry: true`, `justMyCode: true`

### `getExecutableSearchPaths` (L609-624)
- Returns non-empty array; includes path derived from `JAVA_HOME` env when set

### `supportsAttach` (L626-630)
- Returns `true`

### `transformAttachConfig` (L632-687)
- Sets `type: 'java'`, `request: 'attach'`, maps `host`/`port`
- `host` defaults to `'localhost'` when omitted
- `sourcePaths`, `stopOnEntry`, `cwd`, `env`, `timeout` passed through; omitted when not provided

### `getDefaultAttachConfig` (L689-696)
- `request: 'attach'`, `host: 'localhost'`

### `getDefaultExecutableName` (L698-707)
- `'java.exe'` on win32, `'java'` elsewhere

### `getFeatureRequirements` (L727-748)
- `CONDITIONAL_BREAKPOINTS` → 1 requirement, type `'dependency'`, description contains `'JDK'`, required
- `EXCEPTION_BREAKPOINTS` → 1 requirement, description contains `'JDI'`, required
- `STEP_BACK` → empty array

## Key Patterns
- **Conditional test branching** for `buildAdapterCommand`: gracefully handles both compiled and uncompiled JDI bridge environments using try/catch inside tests (L354-365, L382-399, L404-420).
- **EventEmitter-based process mock**: Simulates `child_process` subprocess with stdout/stderr EventEmitter and async `nextTick` event emission for version string parsing.
- **`vi.stubEnv`** used to control `JAVA_HOME`, `PATH`, and `MCP_DEBUGGER_MAIN_PID` per-test; cleaned up by `vi.unstubAllGlobals()` in `afterEach`.
