# packages\adapter-rust\tests\rust-adapter.test.ts
@source-hash: 3b91ef30808172bf
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:46Z

## Purpose
Vitest test suite for the Rust debug adapter package, covering `RustDebugAdapter` and `RustAdapterFactory`. Uses module-level mocks to make environment probes hermetic (no real toolchain required).

## Module-level Mocks (L20–30)
Two `vi.mock` calls intercept real environment probes before any test runs:
- `../src/utils/codelldb-resolver.js`: `resolveCodeLLDBExecutable` → returns `'/mock/vendor/codelldb'`; `getCodeLLDBVersion` → returns `'1.11.0'`
- `../src/utils/rust-utils.js`: `checkCargoInstallation` → returns `true`; `getCargoVersion` → returns `'cargo 1.99.0'`; `getRustHostTriple` → returns `'x86_64-unknown-linux-gnu'`

Both mocks use `importOriginal` spread so non-mocked exports remain intact.

## Shared Mock Fixture (L33–62)
`mockDependencies: AdapterDependencies` — module-level constant providing full stub implementations of:
- `fileSystem`: all fs methods as `vi.fn()`
- `logger`: `info`, `warn`, `error`, `debug` as `vi.fn()`
- `environment`: `get` delegates to `process.env[key]`, `getAll` returns `process.env`, `getCurrentWorkingDirectory` returns `process.cwd()`

## Test Suite: `RustDebugAdapter` (L64–260)

### `beforeEach` (L67–70)
Clears all mocks (`vi.clearAllMocks()`) and re-creates `adapter = new RustDebugAdapter(mockDependencies)`.

### Basic Properties (L72–82)
- Verifies `adapter.language === DebugLanguage.RUST` and `adapter.name === 'Rust Debug Adapter'`
- Verifies initial state is `AdapterState.UNINITIALIZED` and `isReady()` returns `false`

### Capabilities (L84–108)
- Asserts `supportsFeature` returns `true` for: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `DATA_BREAKPOINTS`, `DISASSEMBLE_REQUEST`, `LOG_POINTS`
- Asserts `supportsFeature(DebugFeature.STEP_BACK)` returns `false`
- Asserts `getCapabilities()` returns object with expected booleans including `supportsStepBack: false`

### `buildAdapterCommand` (L110–182)
Tests spy on the private method `resolveCodeLLDBExecutableSync` via type cast to `unknown` then to an interface (L113, L143, L164). Each test calls `vi.restoreAllMocks()` at end.
- **Success case (L111–139)**: mock returns `'/path/to/codelldb'`; asserts `command.command === '/path/to/codelldb'`, `command.args === ['--port', 5678]`, `env.RUST_BACKTRACE` defined; on win32 also checks `LLDB_USE_NATIVE_PDB_READER === '1'`
- **CodeLLDB not found (L141–160)**: mock returns `null`; expects throw `'CodeLLDB executable not found'`
- **Invalid port (L162–181)**: port `0`; expects throw `'Valid TCP port required'`

### `transformLaunchConfig` (L184–233)
- **Explicit program (L185–203)**: config with `program: './target/debug/myapp'`; asserts `type === 'lldb'`, `request === 'launch'`, program contains `'myapp'`, args/env passed through, `sourceLanguages === ['rust']`
- **Cargo config (L205–224)**: config with `cargo: { bin, release, build }`; asserts program path contains `path.join('target', 'release', 'my_binary')`; on win32 also checks `.exe`; asserts `cargo` field preserved and `sourceLanguages === ['rust']`
- **No program (L226–232)**: expects rejection with `'No program specified'`

### Connection Management (L235–247)
- Calls `connect('127.0.0.1', 5678)` then `disconnect()`; asserts `isConnected()` and `getState()` transition through `CONNECTED` → `DISCONNECTED`

### Error Messages (L249–259)
- `translateErrorMessage(new Error('codelldb not found'))` should contain `'npm run build:adapter'`
- `translateErrorMessage(new Error('cargo not found'))` should contain `'rustup.rs'`

## Test Suite: `RustAdapterFactory` (L262–312)

### `beforeEach` (L265–267)
Creates `factory = new RustAdapterFactory()` (no deps needed for factory construction).

- **createAdapter (L269–272)**: `factory.createAdapter(mockDependencies)` returns `RustDebugAdapter` instance
- **getMetadata (L274–281)**: asserts `language === DebugLanguage.RUST`, `displayName === 'Rust'`, `fileExtensions` contains `'.rs'`, `description` contains `'CodeLLDB'`
- **validate success (L283–298)**: module mocks active → `result.valid === true`, `errors/warnings` empty, `details` matches mock values including `platform` and `arch`
- **validate failure (L300–311)**: overrides `resolveCodeLLDBExecutable` with `mockResolvedValueOnce(null)` and `checkCargoInstallation` with `mockResolvedValueOnce(false)`; asserts `valid === false`, errors contain `'CodeLLDB not found'`, warnings contain `'Cargo not found'`

## Key Patterns
- Private method spy pattern: cast adapter to `unknown` then to interface exposing the private method (L113, L143, L164) — avoids TypeScript access restrictions in tests
- `importOriginal` spread pattern ensures non-mocked exports from utility modules remain functional
- Platform-conditional assertions (L132–134, L218–220) accommodate win32 differences
- `mockResolvedValueOnce` used in L303–304 to override module-level mocks for a single test
