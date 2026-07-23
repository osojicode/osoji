# packages\adapter-dotnet\tests\unit\dotnet-adapter-factory.test.ts
@source-hash: 5b39320b69cfef20
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:11Z

## Unit Tests: DotnetAdapterFactory

Tests for `DotnetAdapterFactory` class covering adapter instantiation, metadata retrieval, and environment validation logic.

### Test Structure
- **Suite**: `DotnetAdapterFactory` (L30–82)
- **Setup**: `beforeEach` (L31–34) clears all mocks and resets `findNetcoredbgExecutableMock` before each test

### Helper
- **`createDependencies()`** (L16–28): Factory for stub `AdapterDependencies` with no-op `fileSystem`, `environment` (returns `undefined`/`{}`/`process.cwd()`), and `logger` (no-op methods).

### Test Cases

| Test | Lines | Description |
|---|---|---|
| `creates DotnetDebugAdapter instances with provided dependencies` | L36–41 | Asserts `factory.createAdapter(deps)` returns a `DotnetDebugAdapter` instance |
| `returns accurate adapter metadata` | L43–55 | Asserts `getMetadata()` returns `{ language: DebugLanguage.DOTNET, displayName: '.NET/C#', version: '0.2.0', author: 'mcp-debugger team', fileExtensions: ['.cs', '.vb', '.fs'] }` |
| `validates environment when netcoredbg is available` | L57–71 | Mocks `findNetcoredbgExecutable` to resolve with `/path/to/netcoredbg`; asserts `validate()` returns `{ valid: true, errors: [], warnings: [], details: { debuggerPath, backend: 'netcoredbg', platform } }` |
| `fails validation when no debugger is found` | L73–81 | Mocks `findNetcoredbgExecutable` to reject; asserts `validate()` returns `{ valid: false }` with error message `'netcoredbg not found'` |

### Mocking Strategy
- `../../src/utils/dotnet-utils.js` is fully mocked via `vi.mock` (L8–12), replacing `findNetcoredbgExecutable`, `findDotnetBackend`, and `listDotnetProcesses` with `vi.fn()` stubs.
- Only `findNetcoredbgExecutable` mock is exercised in these tests; the others are stubbed but unused.

### Key Dependencies
- `DotnetAdapterFactory` (SUT): `../../src/DotnetAdapterFactory.js`
- `DotnetDebugAdapter` (instanceof check): `../../src/DotnetDebugAdapter.js`
- `findNetcoredbgExecutable` (mocked): `../../src/utils/dotnet-utils.js`
- `DebugLanguage.DOTNET` from `@debugmcp/shared`: used in metadata assertion (L49)

### Notable Patterns
- Uses Vitest (`vi.mock`, `vi.mocked`, `vi.clearAllMocks`) for all mocking
- `AdapterDependencies` is imported as a type only (L2)
- `createDependencies` uses `as unknown` cast for `fileSystem` (L17), indicating interface flexibility or incomplete stub
- Metadata version `'0.2.0'` (L51) is a hardcoded assertion — will fail if factory version changes