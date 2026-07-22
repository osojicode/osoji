# tests\adapters\go\unit\go-adapter-factory.test.ts
@source-hash: acd2796048e86b19
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:26Z

## Purpose
Unit test suite for `GoAdapterFactory` and indirectly `GoDebugAdapter` from the `@debugmcp/adapter-go` package. Tests factory creation, metadata retrieval, and environment validation (Go toolchain + Delve debugger).

## Test Structure

### Top-Level Suite: `GoAdapterFactory` (L50–254)
Uses Vitest with `beforeEach`/`afterEach` clearing all mocks and resetting globals.

### Mock Setup
- **`child_process.spawn`** is mocked globally via `vi.mock` (L9–15), allowing per-test `mockSpawn.mockImplementation(...)` overrides.
- **`fs.promises.access`** is spied on per-test to simulate tool presence/absence.
- **`createMockDependencies()`** (L19–48): Factory helper returning a full `AdapterDependencies` stub with no-op filesystem, vi.fn() logger, and real `process.env`/`process.cwd()` environment.

### `createAdapter` Tests (L63–73)
- Verifies `factory.createAdapter(deps)` returns a `GoDebugAdapter` instance.
- Verifies `adapter.language` equals `DebugLanguage.GO`.

### `getMetadata` Tests (L75–96)
- Checks `language === DebugLanguage.GO`, `displayName === 'Go'`, `version === '0.1.0'`.
- Checks `description` contains `'Delve'`, `fileExtensions` contains `'.go'`.
- Checks `documentationUrl` contains `'github.com'`.
- Checks `icon` is defined and contains `'data:image/svg+xml'`.

### `validate` Tests (L98–253)
Tests the async `factory.validate()` method against various environment configurations using `mockSpawn` patterns:

| Test | fs.access | spawn behavior | Expected |
|---|---|---|---|
| Go + Delve available (L99–130) | resolves | `go version` → `go1.21.0`, `dlv version` → `1.21.0`, exit 0 | `valid: true`, 0 errors, `details.goPath`/`dlvPath` defined |
| Go not found (L132–141) | rejects | N/A (spawn not called) | `valid: false`, errors contain `'not found'` |
| Go version too old (L143–170) | resolves | `go version` → `go1.16.0` | `valid: false`, errors include `'1.18'` (minimum version) |
| Delve not found (L172–198) | resolves for go, rejects for dlv | `go version` → `go1.21.0` | errors include `'Delve'` or `'dlv'` |
| Delve no DAP support (L200–231) | resolves | `dlv version` → `1.0.0`, `dlv dap --help` exits 1 | `valid: false`, errors include `'DAP'` |
| Platform info in details (L233–252) | resolves | `go version go1.21.0`, exit 0 | `details.platform`, `.arch`, `.timestamp` populated |

### Spawn Mock Pattern
`mockSpawn` returns an `EventEmitter` with `.stdout` and `.stderr` as child `EventEmitter`s (L103–106). Version data is emitted via `process.nextTick` for async simulation. The mock inspects `cmd` (string includes `'dlv'`) and `args[0]` (`'version'`) to produce branched output.

## Key Dependencies
- `@debugmcp/adapter-go`: `GoAdapterFactory`, `GoDebugAdapter` — the subjects under test.
- `@debugmcp/shared`: `AdapterDependencies` type, `DebugLanguage` enum.
- `child_process.spawn`: mocked globally; `mockSpawn` (L17) is the typed reference.
- `node:fs`: `fs.promises.access` is spied on to simulate binary availability.

## Notable Patterns
- `DebugLanguage.GO` is the discriminant used in both `createAdapter` and `getMetadata` assertions.
- Minimum Go version enforced is `1.18` (inferred from L169 error string check).
- Delve DAP support is validated by running `dlv dap --help` and checking exit code.
- `result.details` carries `goPath`, `dlvPath`, `platform`, `arch`, `timestamp` — all asserted across tests.
