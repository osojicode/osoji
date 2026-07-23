# tests\adapters\java\unit\java-debug-adapter.test.ts
@source-hash: 79deee40c46513be
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:39Z

## JavaDebugAdapter Unit Tests

Comprehensive unit test suite for `JavaDebugAdapter` from `@debugmcp/adapter-java`. Tests cover adapter lifecycle, DAP protocol event handling, capability introspection, configuration transformation, and error translation. Uses Vitest with `child_process.spawn` mocked globally.

### Test Infrastructure

**`child_process` mock** (L9–15): Vitest async factory mock replacing `spawn` with `vi.fn()`. Actual module spread to preserve other exports.

**`mockSpawn`** (L17): Typed reference to the mocked `spawn` for per-test `.mockImplementation(...)`.

**`createMockDependencies()`** (L19–48): Factory returning a full `AdapterDependencies` stub:
- `fileSystem`: All async no-ops; `exists`/`pathExists`/`existsSync` return `false`.
- `logger`: All four levels are `vi.fn()` (used to assert warning calls).
- `environment`: Delegates to live `process.env` and `process.cwd()`.

**Setup/teardown** (L54–63): `beforeEach` creates a fresh adapter + dependencies and clears all mocks. `afterEach` clears mocks and unstubs globals.

---

### Test Groups

#### `basic properties` (L65–81)
- `language` → `DebugLanguage.JAVA`
- `name` → `'Java Debug Adapter (JDI)'`
- `getState()` → `AdapterState.UNINITIALIZED` initially
- `isReady()` → `false` initially

#### `initialize` (L83–158)
Mock pattern: `spawn` returns an `EventEmitter` with `.stdout`/`.stderr` sub-emitters; uses `process.nextTick` to simulate async output.
- Success path (L84–101): stderr emits Java 17 version string, process exits 0 → state becomes `READY`, `isReady()` true.
- Event emission (L103–120): `'initialized'` event fired on success.
- Failure path (L122–136): spawn emits `'error'` (`ENOENT`), `PATH`/`JAVA_HOME` stubbed empty → rejects, state becomes `ERROR`.
- Old Java warning (L138–157): Java 8 version string (`1.8.0_292`) → still `READY` but `logger.warn` called with `'Java 11+ recommended'`.

#### `dispose` (L160–187)
- State resets to `UNINITIALIZED` after initialize→dispose cycle.
- `'disposed'` event emitted.

#### `connect/disconnect` (L189–219)
- `connect('127.0.0.1', 38000)` → `CONNECTED`, `isConnected()` true, `'connected'` event.
- `disconnect()` → `DISCONNECTED`, `isConnected()` false, `'disconnected'` event.

#### `getRequiredDependencies` (L221–228)
- Returns array of length 1; entry has `name: 'JDK'` and `required: true`.

#### `supportsFeature` (L230–258)
Supported: `CONDITIONAL_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `TERMINATE_REQUEST`.
Unsupported: `FUNCTION_BREAKPOINTS`, `STEP_BACK`, `DATA_BREAKPOINTS`.

#### `getCapabilities` (L260–282)
- Validates boolean capability flags (configurationDone, functionBPs false, conditionalBPs, evaluateForHovers, setVariable false, terminateRequest, stepBack false, logPoints false).
- `exceptionBreakpointFilters` has exactly 2 entries: `'caught'` (index 0) and `'uncaught'` (index 1).

#### `translateErrorMessage` (L284–321)
Maps specific error strings to user-friendly messages:
- `'JDI bridge not compiled'` → contains `'JDI bridge not compiled'` and `'build:adapter'`
- `'java: command not found'` → `'Java not found'`
- `'permission denied'` → `'Permission denied'`
- `'java.lang.ClassNotFoundException'` → `'class not found'`
- `'java.lang.NoClassDefFoundError'` → `'class not found'`
- Unknown error → passes through unchanged.

#### `getInstallationInstructions` / `getMissingExecutableError` (L323–338)
- Instructions contain `'JDK'`, `'adoptium'`, `'build:adapter'`.
- Missing executable error contains `'Java not found'`, `'adoptium'`.

#### `buildAdapterCommand` (L340–421)
Environment-conditional tests (JDI bridge may not be compiled):
- With valid args: if bridge compiled → `result.command` truthy, `result.args` contains `'JdiDapServer'`; if not → throws `/JDI bridge not compiled/`.
- Port 0: throws matching `/JDI bridge not compiled|Valid TCP port/`.
- `MCP_DEBUGGER_MAIN_PID='424242'` → `--owner-pid 424242` in args (L380–400).
- `MCP_DEBUGGER_MAIN_PID` unset → falls back to `String(process.ppid)` (L402–421).

#### `transformLaunchConfig` (L424–488)
- Base transform: `type: 'java'`, `request: 'launch'`.
- `.java` file path (`src/com/example/Main.java`) → `mainClass: 'Main'` (basename without extension).
- Fully qualified class name (`com.example.Main`) → passed through as `mainClass`.
- `stopOnEntry` defaults to `true`; can be overridden to `false`.
- `classpath` and `sourcePath` pass through.

#### `handleDapEvent` (L490–578, L709–725)
DAP event → adapter state transitions and re-emitted events:
- `'stopped'` → `DEBUGGING`, `getCurrentThreadId()` returns `body.threadId`, `'stopped'` event.
- `'continued'` → `DEBUGGING`, `'continued'` event.
- `'terminated'` → `DISCONNECTED`, `'terminated'` event.
- `'exited'` → `'exited'` event, no state assertion.
- `'thread'` → `'thread'` event.
- `'output'` → `'output'` event.
- `'breakpoint'` → `'breakpoint'` event, called with full event object.

#### `sendDapRequest` (L580–585)
Always rejects with `'DAP request forwarding not implemented'`.

#### `handleDapResponse` (L587–599)
No-op; must not throw (responses handled by ProxyManager per inline comment).

#### `getDefaultLaunchConfig` (L601–607)
`stopOnEntry: true`, `justMyCode: true`.

#### `getExecutableSearchPaths` (L609–624)
- Returns non-empty array.
- When `JAVA_HOME` is set to `/custom/jdk`, array includes path containing `custom/jdk` (cross-platform separator normalized).

#### `supportsAttach` (L626–630)
Returns `true`.

#### `transformAttachConfig` (L632–687)
- Sets `type: 'java'`, `request: 'attach'`, mirrors `host`/`port`.
- Defaults `host` to `'localhost'`.
- Passes through `sourcePaths`, `stopOnEntry`, `cwd`, `env`, `timeout` when provided.
- Omits all optional fields when absent (`timeout` not mandatory).

#### `getDefaultAttachConfig` (L689–696)
`request: 'attach'`, `host: 'localhost'`.

#### `getDefaultExecutableName` (L698–707)
`'java.exe'` on win32, `'java'` elsewhere.

#### `getFeatureRequirements` (L727–748)
- `CONDITIONAL_BREAKPOINTS` → 1 requirement, `type: 'dependency'`, description contains `'JDK'`, `required: true`.
- `EXCEPTION_BREAKPOINTS` → 1 requirement, description contains `'JDI'`, `required: true`.
- `STEP_BACK` (unsupported) → empty array.

---

### Key Dependencies
- `@debugmcp/shared`: `AdapterDependencies` (type), `AdapterState`, `DebugLanguage`, `DebugFeature` enums.
- `@debugmcp/adapter-java`: `JavaDebugAdapter` class under test.
- `child_process.spawn`: Mocked for `initialize()` Java version check.
- `MCP_DEBUGGER_MAIN_PID` env var: Consumed by `buildAdapterCommand` for owner-pid lifecycle management.
