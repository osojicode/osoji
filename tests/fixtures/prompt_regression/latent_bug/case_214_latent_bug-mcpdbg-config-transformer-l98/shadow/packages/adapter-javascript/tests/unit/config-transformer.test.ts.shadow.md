# packages\adapter-javascript\tests\unit\config-transformer.test.ts
@source-hash: 34f640512324797d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:45Z

## Unit Tests: `config-transformer` utilities

Tests for three utility functions exported from `../../src/utils/config-transformer.js`:
- `determineOutFiles` — resolves output file globs
- `isESMProject` — detects ESM project indicators
- `hasTsConfigPaths` — detects TypeScript path aliases

### MockFileSystem (L14–39)
Local test double implementing the `FileSystem` interface from `@debugmcp/shared`. Supports injectable mocks for:
- `existsSync(path)` via `setExistsMock` (L18–20)
- `readFileSync(path, encoding)` via `setReadFileMock` (L22–24)

Default behavior (no mock set): `existsSync` returns `false`, `readFileSync` returns `''`.

Each `describe` block uses `beforeEach`/`afterEach` to inject and restore the file system via `setDefaultFileSystem`.

---

### Test Suite: `determineOutFiles` (L41–50)
- **User-provided outFiles** (L42–45): passes custom array `['dist/**/*.js', '!**/node_modules/**']` → returned as-is.
- **Default outFiles** (L47–49): called with no args → returns `['**/*.js', '!**/node_modules/**']`.

---

### Test Suite: `isESMProject` (L52–130)
Uses `projDir = <cwd>/proj-esm`, `programDir = projDir/src`.

| Test | Condition | Expected |
|------|-----------|----------|
| L70–72 | Program file extension `.mjs` | `true` |
| L74–76 | Program file extension `.mts` | `true` |
| L78–88 | `package.json` in `programDir` with `"type": "module"` | `true` |
| L90–100 | `package.json` in `projDir` (cwd) with `"type": "module"` | `true` |
| L102–112 | `tsconfig.json` in `programDir` with `compilerOptions.module: "ESNext"` | `true` |
| L114–124 | `tsconfig.json` in `projDir` with `compilerOptions.module: "NodeNext"` | `true` |
| L126–129 | No indicators present | `false` |

---

### Test Suite: `hasTsConfigPaths` (L132–187)
Uses `projDir = <cwd>/proj-tspaths`. Tests only check `tsconfig.json` at `projDir` root.

| Test | Condition | Expected |
|------|-----------|----------|
| L149–165 | `tsconfig.json` has non-empty `compilerOptions.paths` | `true` |
| L167–181 | `tsconfig.json` has empty `compilerOptions.paths: {}` | `false` |
| L183–186 | `tsconfig.json` missing entirely | `false` |

---

### Key Patterns
- **FileSystem injection**: `setDefaultFileSystem` (from the module under test) allows swapping the fs abstraction per test; `NodeFileSystem` is restored in `afterEach` to avoid state leakage between suites.
- **String comparison guard**: mock callbacks use `String(p) === pkgPath` to match specific paths, returning `''` for all others.
- All tests are synchronous; no async/await.