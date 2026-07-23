# tests\adapters\go\unit\go-debug-adapter.test.ts
@source-hash: 694b80b036bb2f22
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:58Z

## Unit Tests: GoDebugAdapter

Unit test suite for the `GoDebugAdapter` class from `@debugmcp/adapter-go`, validating all lifecycle, capability, event handling, and command-building behaviors.

### Test Structure

**File:** `tests/adapters/go/unit/go-debug-adapter.test.ts`

All tests are grouped under `describe('GoDebugAdapter')` (L50) with the following sub-suites:

---

### Setup / Teardown

- **`createMockDependencies()` (L19–48):** Factory returning a full `AdapterDependencies` stub with no-op `fileSystem` methods, `vi.fn()` logger, and real `process.env`/`process.cwd()` environment.
- **`beforeEach` (L54–58):** Clears all mocks, recreates `mockDependencies` and `adapter`.
- **`afterEach` (L60–63):** Clears mocks and unstubs globals.
- **`child_process` mock (L9–15):** `spawn` is replaced with `vi.fn()`. The original module is spread to preserve other exports.
- **`mockSpawn` (L17):** Typed reference to the mocked `spawn` for per-test configuration.

---

### Test Suites

#### `basic properties` (L65–81)
- `adapter.language` → `DebugLanguage.GO`
- `adapter.name` → `'Go Debug Adapter (Delve)'`
- `adapter.getState()` → `AdapterState.UNINITIALIZED` on construction
- `adapter.isReady()` → `false` initially

#### `initialize` (L83–138)
- **Success path (L84–108):** Mocks `fs.promises.access` to resolve, `mockSpawn` emits `'go version go1.21.0 darwin/arm64\n'` on stdout then exits 0. Expects `AdapterState.READY` and `isReady() === true`.
- **`initialized` event (L110–129):** Same mock setup; attaches listener to `'initialized'` event and verifies it fires.
- **Failure path (L131–137):** Mocks `fs.promises.access` to reject, stubs PATH to `''`; expects `initialize()` to throw and state to be `AdapterState.ERROR`.

#### `dispose` (L140–168)
- **State reset (L141–159):** Initializes adapter to `READY`, calls `dispose()`, expects state `UNINITIALIZED`.
- **`disposed` event (L161–167):** Attaches listener to `'disposed'` before calling `dispose()` (without prior init); expects event fires.

#### `connect/disconnect` (L170–200)
- `connect('127.0.0.1', 38000)` → `AdapterState.CONNECTED`, `isConnected() === true`
- `'connected'` event is emitted on connect
- `disconnect()` after connect → `AdapterState.DISCONNECTED`, `isConnected() === false`
- `'disconnected'` event is emitted on disconnect

#### `getRequiredDependencies` (L202–211)
- Returns array of length 2: `{ name: 'Go', required: true }` and `{ name: 'Delve (dlv)', required: true }`

#### `supportsFeature` (L213–233)
- Supported: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `LOG_POINTS`, `TERMINATE_REQUEST`
- Not supported: `STEP_BACK` (requires `rr`)

#### `getCapabilities` (L235–257)
- Full capabilities object checks: `supportsConfigurationDoneRequest`, `supportsFunctionBreakpoints`, `supportsConditionalBreakpoints`, `supportsEvaluateForHovers`, `supportsSetVariable`, `supportsLogPoints`, `supportsTerminateRequest` → all `true`; `supportsStepBack` → `false`
- `exceptionBreakpointFilters` has 2 entries with filters `'panic'` and `'fatal'`

#### `translateErrorMessage` (L259–295)
Tests error message translation patterns:
- `'dlv: command not found'` → contains `'Delve debugger not found'`
- `'go: command not found'` → contains `'Go not found'`
- `'permission denied'` → contains `'Permission denied'`
- `'could not launch process: exit status 1'` → contains `'Could not launch process'`
- `'could not attach to process'` → contains `'Could not attach'`
- Unknown errors → passed through as-is

#### `getInstallationInstructions` (L297–304)
- Result contains `'go.dev'`, `'delve'`, `'go install'`

#### `getMissingExecutableError` (L306–312)
- Result contains `'Go not found'` and `'go.dev'`

#### `handleDapEvent` (L314–414)
Tests DAP event dispatch:
- `'stopped'` event (L315–328): emits `'stopped'`, state → `AdapterState.DEBUGGING`; body has `reason: 'breakpoint', threadId: 7`
- `'continued'` event (L330–343): emits `'continued'`, state stays `AdapterState.DEBUGGING`
- `'terminated'` event (L345–357): emits `'terminated'`, state → `AdapterState.DISCONNECTED`
- `'exited'` event (L359–371): emits `'exited'` with `exitCode: 0`
- `'thread'` event (L373–385): emits `'thread'` with `reason: 'started', threadId: 1`
- `'output'` event (L387–399): emits `'output'` with `category: 'stdout'`
- `'breakpoint'` event (L401–413): emits `'breakpoint'` with `reason: 'changed'`

#### `getFeatureRequirements` (L416–442)
- `CONDITIONAL_BREAKPOINTS` → 1 req, `type: 'dependency'`, description contains `'Delve 1.6'`
- `LOG_POINTS` → 1 req, `type: 'version'`, description contains `'Delve 1.7'`
- `STEP_BACK` → 1 req, `type: 'configuration'`, `required: false`
- `FUNCTION_BREAKPOINTS` → empty array

#### `buildAdapterCommand` (L444–473)
- Mocks `fs.promises.access` and spawn; calls `buildAdapterCommand` with full config including `executablePath: '/home/user/go/bin/dlv'`, host, port, logDir, scriptPath.
- Expects `command.command === '/home/user/go/bin/dlv'`; `command.args` contains `'dap'` and `'--listen=127.0.0.1:38000'`

#### `transformLaunchConfig` (L475–500)
- Generic config → `{ type: 'go', request: 'launch', mode: 'debug', program: '/app/main.go' }`
- Config with `mode: 'test'` → `transformed.mode === 'test'`

---

### Key Patterns
- `mockSpawn` is configured per-test as an `EventEmitter`-based process stub emitting stdout data and exit events via `process.nextTick`.
- `fs.promises.access` is spied on per-test to control Go/Delve availability detection.
- All adapter event listeners use `adapter.on(...)` (EventEmitter interface).
- `vi.stubEnv('PATH', '')` used in error path to simulate missing executables.
