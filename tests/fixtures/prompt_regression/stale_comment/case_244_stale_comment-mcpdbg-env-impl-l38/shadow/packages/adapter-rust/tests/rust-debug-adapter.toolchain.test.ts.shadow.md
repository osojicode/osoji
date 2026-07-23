# packages\adapter-rust\tests\rust-debug-adapter.toolchain.test.ts
@source-hash: f6b8bfdab99c64b2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:13Z

## Purpose

Vitest test suite for `RustDebugAdapter` covering toolchain detection, environment validation, DAP protocol operations, launch configuration transformation, CodeLLDB path handling, and adapter capabilities/metadata.

## Test Structure

Top-level `describe`: `'RustDebugAdapter toolchain logic'` (L78–541)

### Mocked Modules (L10–30)
All utility modules are fully mocked via `vi.mock`:
- `../src/utils/rust-utils.js` → `checkCargoInstallation`, `checkRustInstallation`, `getRustHostTriple`, `findDlltoolExecutable`
- `../src/utils/codelldb-resolver.js` → `resolveCodeLLDBExecutable`
- `../src/utils/binary-detector.js` → `detectBinaryFormat`
- `../src/utils/cargo-utils.js` → `findCargoProjectRoot`, `getDefaultBinary`, `needsRebuild`, `buildCargoProject`

### `createDependencies()` (L47–76)
Factory returning a full `AdapterDependencies` mock object with:
- `fileSystem`: all methods are `vi.fn()`
- `logger`: `info`, `warn`, `error`, `debug` as `vi.fn()`
- `environment`: `get` delegates to `process.env[key]`, `getAll` returns `process.env`, `getCurrentWorkingDirectory` returns `process.cwd()`

### `beforeEach` (L82–100)
Resets all mocks and stubs env vars `MCP_RUST_ALLOW_PREBUILT`, `MCP_RUST_EXECUTABLE_PLACEHOLDER`, `RUST_MSVC_BEHAVIOR`, `RUST_AUTO_SUGGEST_GNU` to `undefined`. Recreates `dependencies` and `adapter`.

## Test Groups

### `resolveExecutablePath` (L102–146)
- **Caching** (L103–112): First call resolves to `'cargo'`; second call returns cached result without calling `checkCargoInstallation` again
- **Preferred path** (L114–120): When a real filesystem path exists (created with `fs.mkdtemp`), returns that path directly
- **Missing preferred** (L122–125): Throws `AdapterError` when path does not exist
- **Fallback to rustc** (L127–132): When cargo unavailable but rustc available, returns `'rustc'`
- **Placeholder via env** (L134–145): When `MCP_RUST_ALLOW_PREBUILT=true` + `MCP_RUST_EXECUTABLE_PLACEHOLDER=custom-rust-binary`, returns custom placeholder and logs warning containing `'cargo/rustc not found'`

### `validateEnvironment` (L148–175)
- **CODELLDB_NOT_FOUND + MSVC warning** (L149–160): `resolveCodeLLDBExecutable` returns `null`; triple is `x86_64-pc-windows-msvc` → `valid=false`, error code `'CODELLDB_NOT_FOUND'`, warning code `'RUST_MSVC_TOOLCHAIN'`
- **DLLTOOL_NOT_FOUND** (L162–174): `win32` platform adapter, GNU toolchain, dlltool missing → `valid=true`, warning code `'DLLTOOL_NOT_FOUND'`

### `buildAdapterCommand environment wiring` (L177–211)
- **dlltool injection** (L178–210): Uses `win32` adapter; spies on private `resolveCodeLLDBExecutableSync`; sets `dlltoolPath` directly on instance; verifies `command.env.LLDB_USE_NATIVE_PDB_READER === '1'`, `command.env.DLLTOOL === './dlltool.exe'`, `PATH` starts with `'.'`, and `args === ['--port', 4000]`

### `transformLaunchConfig with Rust sources` (L213–285)
Uses shared `mockBinaryInfo` with `format: 'gnu'`, `debugInfoType: 'dwarf'` (L214–221).
- **Up-to-date build** (L222–240): `needsRebuild=false` → program path set to `target/debug/<bin>[.exe]`, `buildCargoProject` NOT called
- **Stale build** (L242–267): `needsRebuild=true`, `cargo.release: true` → `buildCargoProject` called with `('/workspace/project', logger, 'release')`, result binary path used
- **Build failure** (L269–284): `buildCargoProject` returns `{ success: false, error: 'compile error' }` → throws `'Cargo build failed: compile error'`

### `validateToolchain` (L287–328)
- **MSVC incompatibility** (L288–304): `detectBinaryFormat` returns MSVC binary info → `consumeLastToolchainValidation()` yields `compatible=false`, `toolchain='msvc'`, message contains `'MSVC toolchain'`, has suggestions; second call returns `undefined` (consume-once semantics)
- **Detection failure** (L306–311): `detectBinaryFormat` rejects → `validateToolchain` returns `{ compatible: true, toolchain: 'unknown' }`
- **MSVC behavior error mode** (L313–327): `RUST_MSVC_BEHAVIOR=error` env → `transformLaunchConfig` rejects with `AdapterError`

### `DAP operations and connectivity` (L330–396)
- **Invalid exception filters** (L331–340): `sendDapRequest('setExceptionBreakpoints', { filters: ['unknown'] })` returns `{}` and logs warning containing `'Unknown exception filters'`
- **State transitions via events** (L342–363): After `connect`, `handleDapEvent` with `stopped` → state becomes `AdapterState.DEBUGGING`, `getCurrentThreadId()===21`; `terminated` event → `AdapterState.CONNECTED`, `getCurrentThreadId()===null`
- **DAP error logging** (L365–378): `handleDapResponse` with `success:false` → logger.error called with string containing `'DAP error'`
- **Connection lifecycle** (L380–395): `connect` → `isConnected()=true`, state `CONNECTED`; `disconnect` → `isConnected()=false`, state `DISCONNECTED`; events `'connected'`/`'disconnected'` emitted

### `dependency and path utilities` (L398–492)
- **Required dependencies** (L399–408): `getRequiredDependencies()` includes `CodeLLDB` (installCommand `'npm run build:adapter'`), `Rust`, `Cargo`
- **Executable search paths** (L410–433): Linux adapter with `HOME=/tmp/tester` → paths include `~/.cargo/bin`, `~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin`, entries from `PATH`; Windows adapter with `CARGO_HOME`/`RUSTUP_HOME` → includes `Cargo` and `Program Files` entries
- **Python environment scrubbing** (L435–465): Calls private `configurePythonEnvironment` with a temp dir structure; verifies `PYTHONHOME` removed, `PATH` contains adapter dirs
- **CodeLLDB path sanitization on Windows** (L467–486): Calls private `prepareCodelldbExecutablePath`; result contains `'debug-mcp-codelldb'` and actually exists on disk
- **Metadata helpers** (L488–491): `getAdapterModuleName() === 'codelldb'`, `getAdapterInstallCommand() === 'npm run build:adapter'`

### `adapter messaging and capabilities` (L494–540)
- **Installation guidance** (L495–498): `getInstallationInstructions()` contains `'Install Rust toolchain'`; `getMissingExecutableError()` contains `'Rust toolchain not found'`
- **Error translation** (L500–514): Tests 6 message patterns → expected translated substrings
- **Feature support** (L516–528): `CONDITIONAL_BREAKPOINTS=true`, `REVERSE_DEBUGGING=false`; `DATA_BREAKPOINTS` requirement type `'version'`; `DISASSEMBLE_REQUEST` type `'configuration'`; `LOG_POINTS` description contains `'CodeLLDB'`
- **Default launch config + capabilities** (L530–539): `cwd===process.cwd()`, `stopOnEntry===false`; capabilities include `supportsConditionalBreakpoints=true`, `supportsDisassembleRequest=true`, `supportsSetExpression=false`

## Key Architectural Patterns
- **Platform injection**: `RustDebugAdapter` accepts optional platform string (`'win32'`, `'linux'`) as second constructor argument for cross-platform testing without real OS
- **Private method testing**: Uses `as unknown as { methodName }` casts to access private methods (`resolveCodeLLDBExecutableSync`, `configurePythonEnvironment`, `prepareCodelldbExecutablePath`, `dlltoolPath`)
- **Consume-once state**: `consumeLastToolchainValidation()` is a one-shot accessor (tested at L303)
- **Real filesystem**: Some tests create actual temp directories/files (L115–120, L436–464, L469–486) rather than using the mocked `fileSystem` dependency
- **Env stubbing**: `vi.stubEnv` used to control feature flags without polluting process.env permanently