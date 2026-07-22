# packages\adapter-dotnet\tests\unit\dotnet-adapter-factory.test.ts
@source-hash: 5b39320b69cfef20
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:19Z

## Unit Tests: DotnetAdapterFactory

Tests for `DotnetAdapterFactory` covering adapter instantiation, metadata accuracy, and environment validation logic using mocked `dotnet-utils`.

### Test Structure

**Module mock (L8-12):** `../../src/utils/dotnet-utils.js` is fully mocked via `vi.mock`, replacing `findNetcoredbgExecutable`, `findDotnetBackend`, and `listDotnetProcesses` with `vi.fn()` stubs.

**`findNetcoredbgExecutableMock` (L14):** Typed mock reference used to control resolution/rejection of the executable lookup in individual test cases.

**`createDependencies()` (L16-28):** Factory helper returning a minimal `AdapterDependencies` stub with no-op logger, stub environment (`get` returns `undefined`, `getAll` returns `{}`), and empty fileSystem object.

### Test Suite: `DotnetAdapterFactory` (L30-82)

**`beforeEach` (L31-34):** Clears all mocks and resets `findNetcoredbgExecutableMock` before each test to prevent state leakage.

**Test 1 — Adapter instantiation (L36-41):** Calls `factory.createAdapter(deps)` and asserts the returned value is an instance of `DotnetDebugAdapter`.

**Test 2 — Metadata shape (L43-55):** Calls `factory.getMetadata()` and asserts:
- `language`: `DebugLanguage.DOTNET`
- `displayName`: `'.NET/C#'`
- `version`: `'0.2.0'`
- `author`: `'mcp-debugger team'`
- `fileExtensions`: `['.cs', '.vb', '.fs']`

**Test 3 — Successful validation (L57-71):** Mocks `findNetcoredbgExecutable` to resolve with `'/path/to/netcoredbg'`, then asserts `factory.validate()` returns:
- `valid: true`
- `errors: []`
- `warnings: []`
- `details.debuggerPath`: `'/path/to/netcoredbg'`
- `details.backend`: `'netcoredbg'`
- `details.platform`: `process.platform`

**Test 4 — Failed validation (L73-81):** Mocks `findNetcoredbgExecutable` to reject with `Error('netcoredbg not found')`, then asserts `factory.validate()` returns:
- `valid: false`
- `errors` contains `'netcoredbg not found'`

### Key Dependencies
- `DotnetAdapterFactory` from `../../src/DotnetAdapterFactory.js` — system under test
- `DotnetDebugAdapter` from `../../src/DotnetDebugAdapter.js` — expected return type from `createAdapter`
- `findNetcoredbgExecutable` from `../../src/utils/dotnet-utils.js` — mocked; controls validation outcome
- `AdapterDependencies`, `DebugLanguage` from `@debugmcp/shared` — shared types/enums used in assertions