# tests\adapters\go\unit\go-debug-adapter.test.ts
@source-hash: 694b80b036bb2f22
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:11Z

## Unit Tests: GoDebugAdapter

Unit test suite for the `GoDebugAdapter` class from `@debugmcp/adapter-go`, covering initialization, lifecycle state transitions, DAP event handling, capability/feature reporting, and command construction.

### Test Structure

Top-level `describe('GoDebugAdapter')` (L50–501) with `beforeEach` (L54–58) creating a fresh adapter and mocked dependencies before each test, and `afterEach` (L60–63) clearing mocks and unstubbing globals.

### Key Test Groups

- **basic properties** (L65–81): Verifies `language === DebugLanguage.GO`, `name === 'Go Debug Adapter (Delve)'`, initial state `UNINITIALIZED`, and `isReady() === false`.
- **initialize** (L83–138): Tests state transition to `READY` when Go/Delve are available (mocking `fs.promises.access` and `spawn`); emits `initialized` event; transitions to `ERROR` when Go not found (`fs.promises.access` rejects).
- **dispose** (L140–168): Tests state reset to `UNINITIALIZED` after dispose; emits `disposed` event.
- **connect/disconnect** (L170–200): Tests transitions `→ CONNECTED` / `→ DISCONNECTED`, and emission of `connected` / `disconnected` events. Uses host `127.0.0.1:38000`.
- **getRequiredDependencies** (L202–211): Asserts two required deps — `Go` and `Delve (dlv)`.
- **supportsFeature** (L213–233): Verifies true for `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `LOG_POINTS`, `TERMINATE_REQUEST`; false for `STEP_BACK` (requires rr).
- **getCapabilities** (L235–257): Validates DAP capability flags and two exception breakpoint filters (`panic`, `fatal`).
- **translateErrorMessage** (L259–295): Error string mapping — `dlv: command not found` → contains `'Delve debugger not found'`; `go: command not found` → `'Go not found'`; `permission denied` → `'Permission denied'`; `could not launch process` → `'Could not launch process'`; `could not attach` → `'Could not attach'`; unknown errors pass through unchanged.
- **getInstallationInstructions** (L297–304): Instructions contain `go.dev`, `delve`, `go install`.
- **getMissingExecutableError** (L306–312): Error contains `'Go not found'` and `'go.dev'`.
- **handleDapEvent** (L314–414): Handles `stopped` (→ `DEBUGGING`, emits `stopped`), `continued` (→ `DEBUGGING`, emits `continued`), `terminated` (→ `DISCONNECTED`, emits `terminated`), `exited` (emits `exited`), `thread` (emits `thread`), `output` (emits `output`), `breakpoint` (emits `breakpoint`).
- **getFeatureRequirements** (L416–442): `CONDITIONAL_BREAKPOINTS` → type `dependency`, mentions Delve 1.6; `LOG_POINTS` → type `version`, mentions Delve 1.7; `STEP_BACK` → type `configuration`, `required: false`; `FUNCTION_BREAKPOINTS` → empty array.
- **buildAdapterCommand** (L444–473): After initialization, builds command with `dlv dap --listen=127.0.0.1:38000`, executable at `/home/user/go/bin/dlv`.
- **transformLaunchConfig** (L475–500): Produces `{ type: 'go', request: 'launch', mode: 'debug', program: '/app/main.go' }`; respects `mode: 'test'` passthrough.

### Mock Setup

- **`child_process.spawn`** (L9–17): Fully mocked via `vi.mock`; `mockSpawn` reference at L17 used to configure per-test process emulation with `EventEmitter`-based fake child processes (stdout/stderr emitters + exit event).
- **`createMockDependencies`** (L19–48): Factory returning `AdapterDependencies` with no-op filesystem, vitest spy logger (`info`, `error`, `debug`, `warn`), and real `process.env`/`process.cwd()` for environment.
- **`fs.promises.access`** spy pattern (L86, L111, L132, L142, L446): Used to control whether Go binary is "found" during `initialize()`.

### State Machine Coverage

| Initial | Operation | Expected Final |
|---------|-----------|----------------|
| UNINITIALIZED | initialize() success | READY |
| UNINITIALIZED | initialize() failure | ERROR |
| READY | dispose() | UNINITIALIZED |
| any | connect() | CONNECTED |
| CONNECTED | disconnect() | DISCONNECTED |
| any | handleDapEvent(stopped) | DEBUGGING |
| any | handleDapEvent(continued) | DEBUGGING |
| any | handleDapEvent(terminated) | DISCONNECTED |

### Dependencies
- `vitest` for test runner, mocking, and assertions
- `@debugmcp/shared`: `AdapterDependencies`, `AdapterState`, `DebugLanguage`, `DebugFeature`
- `@debugmcp/adapter-go`: `GoDebugAdapter` (subject under test)
- Node.js `events.EventEmitter` for fake process streams
- Node.js `child_process.spawn` (mocked)
- Node.js `fs` (spied on for `fs.promises.access`)