# packages\adapter-mock\tests\unit\mock-debug-adapter.spec.ts
@source-hash: 86fcfd6965ef06b2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:29Z

## Purpose
Unit test suite for `MockDebugAdapter` verifying adapter lifecycle, state transitions, error scenarios, DAP event handling, feature support reporting, and error message translation.

## Test Suite Structure

### Top-level fixture factory: `createDependencies` (L6-21)
Returns a fully-typed `AdapterDependencies` object with:
- `fileSystem`: empty object cast to `any`
- `networkManager`: `undefined`
- `environment`: stub implementing `get → undefined`, `getAll → {}`, `getCurrentWorkingDirectory → '/tmp'`
- `logger`: three `vi.fn()` mocks — `debug`, `info`, `error`

`deps` is rebuilt in `beforeEach` (L26-28) ensuring test isolation.

---

### Test Cases

| Test | Lines | Key Assertion |
|------|-------|---------------|
| Initialize → READY | L30-41 | State sequence `[INITIALIZING, READY]`; `isReady() === true` |
| Initialize failure | L43-49 | `EXECUTABLE_NOT_FOUND` scenario → rejects with `/Invalid state transition/`; final state `ERROR` |
| Connect / Disconnect | L51-66 | `connectionDelay: 0`; after connect: `isConnected() === true`, state `CONNECTED`; after disconnect: `isConnected() === false`, `getCurrentThreadId() === null`, state `DISCONNECTED`; logger.debug called with exact string `'[MockDebugAdapter] Connect request to 127.0.0.1:5678'` |
| Connection timeout | L68-76 | `CONNECTION_TIMEOUT` scenario → rejects with `{ code: AdapterErrorCode.CONNECTION_TIMEOUT }` |
| DAP event handling | L78-96 | `stopped` event with `threadId: 42` → thread tracked, state `DEBUGGING`; `terminated` event → thread cleared, state `CONNECTED` |
| Feature support | L98-109 | `supportedFeatures: [LOG_POINTS]` config; `supportsFeature(LOG_POINTS) === true`, `supportsFeature(SET_VARIABLE) === false`; `getFeatureRequirements(CONDITIONAL_BREAKPOINTS)` returns array of length 1 with `{ required: true }` |
| Error messages | L111-116 | `getInstallationInstructions()` contains `'built-in'`; `getMissingExecutableError()` contains `'Mock executable not found'`; `translateErrorMessage(new Error('ENOENT: missing file'))` contains `'Mock file not found'` |

---

## Key Dependencies
- **`MockDebugAdapter`** (`../../src/mock-debug-adapter.js`): System under test — the main adapter class
- **`MockErrorScenario`** (`../../src/mock-debug-adapter.js`): Enum used to configure error injection — `EXECUTABLE_NOT_FOUND`, `CONNECTION_TIMEOUT`
- **`DebugFeature`**, **`AdapterState`**, **`AdapterErrorCode`** (`@debugmcp/shared`): Shared enums for features, lifecycle states, and error codes
- **`AdapterDependencies`** (`@debugmcp/shared`): Type for dependency injection shape
- **`vitest`**: Test framework providing `describe`, `it`, `expect`, `beforeEach`, `vi`

## Architectural Notes
- Tests exercise the `stateChanged` event emitter API (L34: `adapter.on('stateChanged', ...)`), verifying ordered state transitions as side effects
- `connectionDelay: 0` is passed in several tests to eliminate async timing delays
- `handleDapEvent` is called with `as any` casts (L83, 91) indicating the public method accepts typed DAP event objects that require casting in test context
- The test at L43-49 demonstrates that `EXECUTABLE_NOT_FOUND` triggers a failed `initialize()` rather than a connect-phase error
- No spy/mock is placed on `MockDebugAdapter` itself — all assertions use the public interface directly