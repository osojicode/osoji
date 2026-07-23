# packages\adapter-dotnet\tests\unit\dotnet-bridge-fallback.test.ts
@source-hash: a6bb732a6a8f78db
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:10Z

## Purpose
Unit test file for the fallback path resolution logic of `netcoredbg-bridge.js` within `DotnetDebugAdapter.buildAdapterCommand`. Isolated from the main test file because `node:fs` must be mocked at the ESM module level before import.

## Architecture / Key Decisions

### Why Separated (L1–6)
ESM modules cannot be spied on after import. This file uses `vi.hoisted` + `vi.mock` to intercept `node:fs.existsSync` before `DotnetDebugAdapter` is imported, enabling control over bridge-script path resolution.

### Hoisted Mock (L11–13)
`existsSyncMock` is created via `vi.hoisted` so it exists before any `vi.mock` factory runs. Typed as `vi.fn<(p: string) => boolean>()`.

### `node:fs` Mock (L15–18)
Replaces both `existsSync` on the named export and on `default` with `existsSyncMock`, while spreading the actual module for all other functions.

### `dotnet-utils` Mock (L21–29)
All utility functions (`findNetcoredbgExecutable`, `findDotnetBackend`, `listDotnetProcesses`, `findPdb2PdbExecutable`, `convertPdbsToTemp`, `getProcessExecutableDir`, `getProcessArchitecture`) are replaced with `vi.fn()` stubs to prevent initialization failures.

## Test Fixtures

### `createDependencies` (L33–45)
Factory returning a minimal `AdapterDependencies` stub:
- `fileSystem`: empty object cast as unknown
- `environment`: `get` returns `undefined`, `getAll` returns `{}`, `getCurrentWorkingDirectory` returns `process.cwd()`
- `logger`: all methods (`info`, `debug`, `error`) are no-ops

### `defaultConfig` (L47–55)
Static config object passed to `buildAdapterCommand`:
- `sessionId`: `'test'`
- `executablePath`: `'/path/to/netcoredbg'`
- `adapterHost`: `'127.0.0.1'`
- `adapterPort`: `9999`
- `logDir`: `'/tmp'`
- `scriptPath`: `'/app.dll'`
- `launchConfig`: `{}`

## Test Suite: `DotnetDebugAdapter bridge fallback resolution` (L57–97)

**Setup (L60–63):** `beforeEach` clears all mocks and creates a fresh `DotnetDebugAdapter` instance.

### Test 1 — Error on no valid path (L65–70)
`existsSyncMock` returns `false` for all calls. Asserts `buildAdapterCommand` throws with message matching `/netcoredbg-bridge\.js not found/`.

### Test 2 — Fallback path used when primary fails (L72–84)
`existsSyncMock` returns `false` on the first call (dev/primary path) and `true` on the second (NPX fallback path). Asserts:
- `existsSyncMock` was called at least twice
- `command.args[0]` contains `'netcoredbg-bridge'`

### Test 3 — Multiple candidates searched (L86–97)
`existsSyncMock` always returns `false`. Calls `buildAdapterCommand` inside try/catch (error expected). Asserts `existsSyncMock` was called **at least 4 times**, confirming the implementation checks ≥4 candidate paths before giving up.

## Dependencies
- `vitest`: `describe`, `it`, `expect`, `beforeEach`, `vi`
- `@debugmcp/shared`: `AdapterDependencies` type
- `../../src/DotnetDebugAdapter.js`: `DotnetDebugAdapter` class under test
- `node:fs` (mocked): `existsSync`
- `../../src/utils/dotnet-utils.js` (mocked): all utility exports

## Invariants
- `existsSyncMock` must be hoisted before `DotnetDebugAdapter` is imported; import order is critical.
- Tests rely on `buildAdapterCommand` checking paths sequentially using `existsSync`, not in parallel.
- The ≥4 path check (Test 3) documents a minimum contract on how many fallback paths the implementation must try.
