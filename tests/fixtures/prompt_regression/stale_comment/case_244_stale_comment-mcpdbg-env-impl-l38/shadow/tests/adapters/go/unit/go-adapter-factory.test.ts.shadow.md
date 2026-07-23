# tests\adapters\go\unit\go-adapter-factory.test.ts
@source-hash: acd2796048e86b19
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:38Z

## Purpose
Unit tests for `GoAdapterFactory` and `GoDebugAdapter` from `@debugmcp/adapter-go`. Validates factory construction, metadata correctness, adapter instantiation, and environment validation logic (Go binary availability, version constraints, Delve DAP support).

## Test Structure

### Mock Setup (L9–17)
- `child_process.spawn` is mocked globally via `vi.mock` with `importOriginal` to preserve non-mocked exports.
- `mockSpawn` is a typed vi mock at L17, used in `validate` tests to simulate process output.

### `createMockDependencies` (L19–48)
Helper that returns a complete `AdapterDependencies` stub:
- `fileSystem`: all async stubs returning empty/false values; `exists` and `pathExists` return `false`, `stat` returns a cast empty object.
- `logger`: vi.fn() stubs for `info`, `error`, `debug`, `warn`.
- `environment`: delegates to real `process.env` and `process.cwd()`.

### Test Suite: `GoAdapterFactory` (L50–253)

**`createAdapter` (L63–73)**
- Verifies `factory.createAdapter(deps)` returns a `GoDebugAdapter` instance (L66).
- Verifies `adapter.language` equals `DebugLanguage.GO` (L71).

**`getMetadata` (L75–96)**
- `language` === `DebugLanguage.GO` (L79)
- `displayName` === `'Go'` (L80)
- `version` === `'0.1.0'` (L81)
- `description` contains `'Delve'` (L82)
- `fileExtensions` contains `'.go'` (L83)
- `documentationUrl` contains `'github.com'` (L88)
- `icon` defined and begins with `'data:image/svg+xml'` (L94)

**`validate` (L98–253)**
Five scenarios, all mocking `fs.promises.access` and `spawn`:

1. **Valid environment** (L99–130): Both Go and Delve accessible, spawn returns version strings with exit 0. Expects `result.valid === true`, empty errors, and `details.goPath`/`details.dlvPath` defined.

2. **Go not found** (L132–141): `fs.promises.access` rejects, `PATH` stubbed empty. Expects `valid === false`, at least one error containing `'not found'`.

3. **Go version too old** (L143–170): Spawn returns `go1.16.0` (below minimum `1.18`). Expects `valid === false`, error containing `'1.18'`.

4. **Delve not found** (L172–198): `fs.promises.access` resolves for Go paths but rejects for `dlv` paths. Spawn returns valid Go version only. Expects error mentioning `'Delve'` or `'dlv'`.

5. **Delve no DAP support** (L200–231): Spawn returns Delve `1.0.0` (old), and `dlv dap --help` exits with code 1. Expects `valid === false`, error containing `'DAP'`.

6. **Platform info in details** (L233–252): Valid spawn setup; checks `result.details.platform === process.platform`, `arch === process.arch`, `timestamp` defined.

## Key Patterns
- `process.nextTick` used inside `mockSpawn.mockImplementation` to simulate async process output before `exit` event, matching real child process behavior.
- `vi.stubEnv('PATH', '')` used in test L134 to simulate missing Go in PATH.
- `vi.spyOn(fs.promises, 'access')` controls binary existence checks without filesystem access.
- `beforeEach`/`afterEach` clear all mocks and unstub globals to prevent test bleed.

## Dependencies
- `@debugmcp/adapter-go`: `GoAdapterFactory`, `GoDebugAdapter` — the subjects under test.
- `@debugmcp/shared`: `AdapterDependencies` (type), `DebugLanguage` (enum with `GO` member).
- `vitest`: test runner, mocking utilities.
- `events.EventEmitter`: used to create mock child_process objects with `stdout`/`stderr` event emitters.
- `child_process.spawn`: mocked entirely.
- `node:fs`: `fs.promises.access` is spied on per-test.