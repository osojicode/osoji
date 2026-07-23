# tests\unit\utils\simple-file-checker.spec.ts
@source-hash: 08d6d896cd5c3ccb
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:54Z

## Unit Tests: `SimpleFileChecker`

Tests for `SimpleFileChecker` and `createSimpleFileChecker` from `src/utils/simple-file-checker.ts`, using Vitest with full dependency injection via mocked interfaces.

### Test Structure

**Test Suite:** `SimpleFileChecker` (L8–179)

Three nested `describe` blocks:

1. **Host Mode (no container)** (L50–115): Tests behavior when `mockEnvironment.get` returns `undefined` (not containerized).
   - `should check file existence without path manipulation` (L56–69): Absolute path passed directly to `pathExists`, result has matching `originalPath` and `effectivePath`.
   - `should handle non-existent files` (L71–83): `pathExists` returns `false`, result reflects `exists: false`.
   - `should handle system errors` (L85–99): `pathExists` rejects, result has `exists: false` and `errorMessage: 'Cannot check file existence: Permission denied'`.
   - `should reject relative paths with helpful error message` (L101–114): Relative path `'src/file.ts'` returns `exists: false`, `errorMessage: 'Path must be absolute. Received: "src/file.ts"'`, and `pathExists` is **not** called.

2. **Container Mode** (L117–172): `MCP_CONTAINER=true`, `MCP_WORKSPACE_ROOT=/workspace`.
   - `should prepend /workspace/ to relative paths` (L127–139): Relative path `'src/file.ts'` → `effectivePath: '/workspace/src/file.ts'`.
   - `should not double-prefix paths already under workspace root (idempotent)` (L142–155): Path already starting with `/workspace/` is not re-prefixed.
   - `should handle any path format (no interpretation)` (L157–171): Windows-style path `C:\Users\test\file.ts` gets a plain `/workspace/` prefix without conversion.

3. **Factory function** (L174–179): `createSimpleFileChecker` returns a `SimpleFileChecker` instance.

### Fixture Setup (L14–48)

`beforeEach` creates full mocks for:
- `mockFileSystem: IFileSystem` — all methods mocked with `vi.fn()`, with typed casts on `pathExists` and `existsSync` (L16–32).
- `mockEnvironment: IEnvironment` — `get`, `getAll`, `getCurrentWorkingDirectory` mocked (L35–39).
- `mockLogger: { debug }` — minimal logger stub (L42–44).
- `checker: SimpleFileChecker` — constructed directly via `new SimpleFileChecker(mockFileSystem, mockEnvironment, mockLogger)` (L47).

### Key Contracts Tested

- `checkExists(path)` returns `{ exists: boolean, originalPath: string, effectivePath: string, errorMessage?: string }`.
- Host mode: paths are used as-is; relative paths are rejected immediately.
- Container mode: controlled via `MCP_CONTAINER` env var; workspace root from `MCP_WORKSPACE_ROOT`; prefix is idempotent.
- Error from `pathExists` is caught and surfaced as `errorMessage: 'Cannot check file existence: <message>'`.
- `createSimpleFileChecker` is a factory that wraps `new SimpleFileChecker(...)`.

### Dependencies

- `SimpleFileChecker`, `createSimpleFileChecker` from `../../../src/utils/simple-file-checker.js`
- `IFileSystem`, `IEnvironment` from `../../../src/interfaces/external-dependencies.js`
- Vitest: `describe`, `it`, `expect`, `beforeEach`, `vi`, `MockedFunction`