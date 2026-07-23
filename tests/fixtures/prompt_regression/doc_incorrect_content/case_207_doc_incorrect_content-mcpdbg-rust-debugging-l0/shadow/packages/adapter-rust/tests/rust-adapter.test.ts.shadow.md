# packages\adapter-rust\tests\rust-adapter.test.ts
@source-hash: 3b91ef30808172bf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:40Z

## Purpose
Test suite for the Rust debug adapter package, covering `RustDebugAdapter` and `RustAdapterFactory`. Validates adapter properties, capabilities, command building, launch config transformation, connection management, error messaging, factory metadata, and environment validation — all in a hermetic environment via mocked toolchain probes.

## Key Mocks (L20–30)
Two module-level `vi.mock` calls make the suite hermetic:
- `../src/utils/codelldb-resolver.js`: `resolveCodeLLDBExecutable` → `'/mock/vendor/codelldb'`, `getCodeLLDBVersion` → `'1.11.0'`
- `../src/utils/rust-utils.js`: `checkCargoInstallation` → `true`, `getCargoVersion` → `'cargo 1.99.0'`, `getRustHostTriple` → `'x86_64-unknown-linux-gnu'`

Both use `importOriginal` to spread original module exports so non-mocked functions remain functional.

## `mockDependencies` (L33–62)
Shared `AdapterDependencies` fixture with `vi.fn()` stubs for:
- `fileSystem`: all standard FS operations
- `logger`: info/warn/error/debug
- `environment`: delegates `get` to `process.env`, `getAll` to `process.env`, `getCurrentWorkingDirectory` to `process.cwd()`

Used in both `RustDebugAdapter` and `RustAdapterFactory` test suites.

## `RustDebugAdapter` Tests (L64–260)

### Basic Properties (L72–82)
- `language` → `DebugLanguage.RUST`
- `name` → `'Rust Debug Adapter'`
- Initial state → `AdapterState.UNINITIALIZED`, `isReady()` → `false`

### Capabilities (L84–108)
- Supported: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `DATA_BREAKPOINTS`, `DISASSEMBLE_REQUEST`, `LOG_POINTS`
- Not supported: `STEP_BACK` (reverse debugging)
- `getCapabilities()` returns object with `supportsConfigurationDoneRequest`, `supportsConditionalBreakpoints`, `supportsFunctionBreakpoints`, `supportsDataBreakpoints`, `supportsDisassembleRequest`, `supportsSteppingGranularity` all `true`; `supportsStepBack` `false`

### `buildAdapterCommand` (L110–182)
Tests spy on the private method `resolveCodeLLDBExecutableSync` via `adapter as unknown as { resolveCodeLLDBExecutableSync: () => string | null }`:
- **Happy path** (L111–139): returns `{ command: '/path/to/codelldb', args: ['--port', 5678], env: {...} }`. Win32: `LLDB_USE_NATIVE_PDB_READER === '1'`. Always: `RUST_BACKTRACE` defined.
- **CodeLLDB not found** (L141–160): mock returns `null` → throws `'CodeLLDB executable not found'`
- **Invalid port** (L162–181): `adapterPort: 0` → throws `'Valid TCP port required'`

### `transformLaunchConfig` (L184–233)
- **Explicit program path** (L185–203): `{ program, args, cwd, env, stopOnEntry }` → result has `type: 'lldb'`, `request: 'launch'`, `program` contains `'myapp'`, `sourceLanguages: ['rust']`
- **Cargo config** (L205–224): `{ cargo: { bin, release, build } }` → `program` contains `path.join('target', 'release', 'my_binary')`; `.exe` suffix on win32; `cargo` and `sourceLanguages` passed through
- **No program** (L226–232): throws `'No program specified'`

### Connection Management (L235–247)
- Start: `isConnected()` → `false`
- After `connect('127.0.0.1', 5678)`: `isConnected()` → `true`, state → `AdapterState.CONNECTED`
- After `disconnect()`: `isConnected()` → `false`, state → `AdapterState.DISCONNECTED`

### Error Messages (L249–259)
- `'codelldb not found'` error → translated message contains `'npm run build:adapter'`
- `'cargo not found'` error → translated message contains `'rustup.rs'`

## `RustAdapterFactory` Tests (L262–312)

- **createAdapter** (L269–272): returns instance of `RustDebugAdapter`
- **getMetadata** (L274–281): `language === DebugLanguage.RUST`, `displayName === 'Rust'`, `fileExtensions` contains `'.rs'`, `description` contains `'CodeLLDB'`
- **validate — success** (L283–298): with mocked probes → `valid: true`, empty errors/warnings, `details` matches mock values plus `process.platform` and `process.arch`
- **validate — failure** (L300–311): overrides mocks per-test (`mockResolvedValueOnce(null)` + `mockResolvedValueOnce(false)`) → `valid: false`, errors include `'CodeLLDB not found'`, warnings include `'Cargo not found'`

## Dependencies
- `vitest`: `describe`, `it`, `expect`, `beforeEach`, `vi`
- `../src/rust-debug-adapter.js`: `RustDebugAdapter`
- `../src/rust-adapter-factory.js`: `RustAdapterFactory`
- `@debugmcp/shared`: `AdapterState`, `DebugLanguage`, `DebugFeature`, `AdapterDependencies`, `AdapterConfig`
- `path` (Node stdlib): used for platform-aware path assertions in `transformLaunchConfig` tests

## Architectural Notes
- `resolveCodeLLDBExecutableSync` is a private method accessed via TypeScript type cast (`as unknown as`) for targeted spy injection (L113, L143, L165).
- Per-test mock overrides via `mockResolvedValueOnce` (L303–304) test failure paths without polluting other tests.
- `vi.restoreAllMocks()` called explicitly after each `buildAdapterCommand` test (L138, L159, L180) to clean spies on the private method.
