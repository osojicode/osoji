# tests\unit\adapters\mock-debug-adapter.test.ts
@source-hash: ebff6ffb5d375b80
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:35Z

## Unit Tests: `MockDebugAdapter`

Tests the `MockDebugAdapter` and `MockErrorScenario` from the `adapter-mock` package, validating adapter lifecycle state transitions, feature support reporting, error message translation, and error scenario injection.

### Test Setup (L5–26)
- `createDependencies()` (L5–15): Factory producing a minimal `AdapterDependencies` object with `vi.fn()` mocked logger methods (`info`, `warn`, `error`, `debug`) and empty/cast stubs for `environment`, `fileSystem`, and `networkManager`.
- `beforeEach` (L20–26): Clears all mocks and constructs a fresh `MockDebugAdapter` with `supportedFeatures: [CONDITIONAL_BREAKPOINTS, LOG_POINTS]` and `connectionDelay: 0`.

### Test Cases

| Test | Lines | What is verified |
|------|-------|-----------------|
| State transitions | L28–37 | `initialize()` → `READY`; `connect('127.0.0.1', 9000)` → `CONNECTED`; `disconnect()` → `DISCONNECTED` |
| Feature support | L39–42 | `supportsFeature(CONDITIONAL_BREAKPOINTS)` → `true`; `supportsFeature(DATA_BREAKPOINTS)` → `false` |
| Error translation | L44–47 | `translateErrorMessage(new Error('ENOENT: file missing'))` → message contains `'Mock file not found'` |
| Error scenario injection | L49–52 | After `setErrorScenario(CONNECTION_TIMEOUT)`, `connect(...)` rejects with `/Connection timeout/` |

### Key Dependencies
- **`MockDebugAdapter`** from `packages/adapter-mock/src/mock-debug-adapter.js` — the system under test.
- **`MockErrorScenario`** — enum/constant used to inject connection failure modes (e.g., `CONNECTION_TIMEOUT`).
- **`AdapterState`**, **`DebugFeature`**, **`AdapterDependencies`** from `@debugmcp/shared` — shared enums and types defining adapter contract.

### Architectural Notes
- `connectionDelay: 0` in the adapter config makes async tests synchronous in practice (no real timing delays).
- `fileSystem` and `networkManager` are cast via `as unknown as ...` — these are unused by `MockDebugAdapter` but required by the `AdapterDependencies` interface shape.
- The test suite covers the full observable contract of `MockDebugAdapter`: state machine, feature querying, error translation, and fault injection — acting as a behavioral specification for the mock adapter.
