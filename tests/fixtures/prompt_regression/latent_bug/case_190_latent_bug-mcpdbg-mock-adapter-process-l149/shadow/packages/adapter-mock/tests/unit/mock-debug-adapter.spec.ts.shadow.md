# packages\adapter-mock\tests\unit\mock-debug-adapter.spec.ts
@source-hash: 86fcfd6965ef06b2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:42Z

## Unit Tests for `MockDebugAdapter`

Tests the `MockDebugAdapter` class from `packages/adapter-mock/src/mock-debug-adapter.ts` using Vitest. Covers adapter lifecycle, state transitions, error scenarios, DAP event handling, feature support, and error translation.

### Test Infrastructure

**`createDependencies` (L6-21):** Factory returning a stub `AdapterDependencies` object with:
- `fileSystem`: empty object cast to `any`
- `networkManager`: `undefined`
- `environment`: stub returning `undefined`/`{}`/`'/tmp'`
- `logger`: three `vi.fn()` spies (`debug`, `info`, `error`)

Each test gets a fresh copy via `beforeEach` (L26-28).

### Test Suite: `MockDebugAdapter` (L23-117)

| Test | Lines | What's verified |
|------|-------|-----------------|
| Initialization to READY | L30-41 | `initialize()` emits `stateChanged` events: `INITIALIZING` → `READY`; `isReady()` returns `true` |
| Init failure on error scenario | L43-49 | `EXECUTABLE_NOT_FOUND` scenario causes `initialize()` to reject with `/Invalid state transition/`; state ends at `AdapterState.ERROR` |
| Connect/disconnect lifecycle | L51-66 | `connect('127.0.0.1', 5678)` → `isConnected()==true`, `CONNECTED` state; `disconnect()` resets connection flags, clears thread ID, sets `DISCONNECTED`; logger.debug called with connect message |
| Connection timeout scenario | L68-76 | `CONNECTION_TIMEOUT` scenario causes `connect()` to reject with `{ code: AdapterErrorCode.CONNECTION_TIMEOUT }` |
| DAP event handling | L78-96 | `handleDapEvent({event:'stopped', body:{threadId:42}})` sets `getCurrentThreadId()==42`, state→`DEBUGGING`; `terminated` event clears thread ID, reverts to `CONNECTED` |
| Feature support config | L98-109 | Constructor `supportedFeatures` option controls `supportsFeature()`; `getFeatureRequirements(CONDITIONAL_BREAKPOINTS)` returns array with one `{required:true}` item |
| Error translation / installation | L111-116 | `getInstallationInstructions()` contains `'built-in'`; `getMissingExecutableError()` contains `'Mock executable not found'`; `translateErrorMessage(ENOENT)` contains `'Mock file not found'` |

### Key Observations
- `MockDebugAdapter` constructor accepts optional second arg (options object) with `connectionDelay` and `supportedFeatures` properties.
- `setErrorScenario(MockErrorScenario.*)` is called before the action that should fail — errors are pre-configured, not thrown inline.
- `handleDapEvent` is a public method accepting raw DAP event objects (cast to `any` in tests).
- `connectionDelay: 0` is set in multiple tests to avoid timing delays.
- State change events follow pattern `('stateChanged', (prev, next) => ...)`.
