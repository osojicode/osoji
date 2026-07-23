# packages\adapter-mock\tests\unit\mock-adapter-factory.test.ts
@source-hash: 4057c911857d5322
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:21Z

## Purpose
Unit tests for `MockAdapterFactory` and `createMockAdapterFactory` from the `adapter-mock` package. Validates factory construction, adapter creation with configuration forwarding, metadata accuracy, and validation behavior.

## Test Structure

### Helper: `createDependencies` (L7–21)
Creates a minimal stub `AdapterDependencies` object extended with a typed `logger`. Used as the dependency injection payload for `factory.createAdapter(...)`.
- `fileSystem`: empty object cast as unknown
- `environment`: stubs `get` (returns `undefined`), `getAll` (returns `{}`), `getCurrentWorkingDirectory` (returns `process.cwd()`)
- `logger`: stubs `info`, `debug`, `error` (all return `undefined`)

### Test Suite: `MockAdapterFactory` (L23–65)

| Test | Line | What is verified |
|---|---|---|
| Creates `MockDebugAdapter` with config | L24–33 | `new MockAdapterFactory({ supportedFeatures: [DebugFeature.LOG_POINTS] })` → `createAdapter()` returns `MockDebugAdapter` instance; `supportsFeature(LOG_POINTS)` is `true` |
| Metadata accuracy | L35–45 | `getMetadata()` returns `{ language: DebugLanguage.MOCK, displayName: 'Mock Debug Adapter', version: '1.0.0', author: 'MCP Debugger Team', fileExtensions: ['.mock', '.test'] }` |
| Validate with defaults | L47–54 | `validate()` resolves to `{ valid: true, errors: [], warnings: [], details: { config: {} } }` |
| `createMockAdapterFactory` helper | L56–65 | Helper factory returns `MockAdapterFactory` instance; config (`SET_VARIABLE` feature) is forwarded to the adapter |

## Key Dependencies
- `MockAdapterFactory`, `createMockAdapterFactory` from `../../src/mock-adapter-factory.js` — subjects under test
- `MockDebugAdapter` from `../../src/mock-debug-adapter.js` — used for `instanceof` assertion
- `AdapterDependencies` (type), `DebugFeature`, `DebugLanguage` from `@debugmcp/shared`

## Notable Patterns
- `createDependencies()` isolates boilerplate stub construction; reused across tests that call `createAdapter()`
- Metadata test uses `toMatchObject` (L38), allowing additional fields on the actual object without failing
- `validate()` test (L47–54) checks `result.details.config` equals `{}`, implying default config produces empty detail map
- No mocking framework used — stubs are plain inline functions