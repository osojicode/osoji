# packages\adapter-rust\tests\rust-debug-adapter.toolchain.test.ts
@source-hash: f6b8bfdab99c64b2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:56Z

## Purpose
Vitest test suite for `RustDebugAdapter` covering toolchain resolution, environment validation, DAP lifecycle, launch config transformation, and capability reporting.

## File Structure
- **Mocks** (L10–30): All four utility modules are fully mocked via `vi.mock`:
  - `../src/utils/rust-utils.js`: `checkCargoInstallation`, `checkRustInstallation`, `getRustHostTriple`, `findDlltoolExecutable`
  - `../src/utils/codelldb-resolver.js`: `resolveCodeLLDBExecutable`
  - `../src/utils/binary-detector.js`: `detectBinaryFormat`
  - `../src/utils/cargo-utils.js`: `findCargoProjectRoot`, `getDefaultBinary`, `needsRebuild`, `buildCargoProject`

- **`createDependencies()` (L47–76)**: Factory returning a full `AdapterDependencies` mock with `fileSystem`, `logger`, and `environment` (all `vi.fn()`). `environment.get` delegates to `process.env`, `getAll` returns `process.env`, `getCurrentWorkingDirectory` returns `process.cwd()`.

- **`beforeEach` (L82–100)**: Clears all mocks, resets all imported mock functions individually, stubs env vars `MCP_RUST_ALLOW_PREBUILT`, `MCP_RUST_EXECUTABLE_PLACEHOLDER`, `RUST_MSVC_BEHAVIOR`, `RUST_AUTO_SUGGEST_GNU` to `undefined`, recreates `dependencies` and `adapter`.

## Test Groups

### `resolveExecutablePath` (L102–146)
- **Cache test (L103–112)**: Confirms result is cached after first call; `checkCargoInstallation` called only once even if second mock returns `false`. Returns `'cargo'`.
- **Preferred executable (L114–120)**: Creates a real temp file; confirms adapter uses it directly.
- **Missing preferred (L122–125)**: Expects `AdapterError` thrown for non-existent path.
- **Fallback to rustc (L127–132)**: Cargo unavailable, rustc available → returns `'rustc'`.
- **Relaxed placeholder (L134–145)**: `MCP_RUST_ALLOW_PREBUILT=true`, `MCP_RUST_EXECUTABLE_PLACEHOLDER=custom-rust-binary` → returns custom placeholder and logs warning containing `'cargo/rustc not found'`.

### `validateEnvironment` (L148–175)
- **CODELLDB_NOT_FOUND + MSVC warning (L149–160)**: `resolveCodeLLDBExecutable` returns `null`, host triple is `x86_64-pc-windows-msvc` → `valid=false`, error code `'CODELLDB_NOT_FOUND'`, warning code `'RUST_MSVC_TOOLCHAIN'`.
- **DLLTOOL_NOT_FOUND (L162–174)**: Win32 adapter, GNU toolchain, `findDlltoolExecutable` returns `undefined` → `valid=true`, warning code `'DLLTOOL_NOT_FOUND'`.

### `buildAdapterCommand` environment wiring (L177–211)
- **dlltool injection (L178–210)**: Win32 adapter; spies on private `resolveCodeLLDBExecutableSync` returning a CodeLLDB path; directly sets `dlltoolPath='./dlltool.exe'` via type cast. Verifies:
  - `command.env.LLDB_USE_NATIVE_PDB_READER === '1'`
  - `command.env.DLLTOOL === './dlltool.exe'`
  - `command.env.PATH` starts with `'.'`
  - `command.args` equals `['--port', 4000]`

### `transformLaunchConfig` (L213–285)
- **mockBinaryInfo (L214–220)**: `{ format: 'gnu', hasPDB: false, hasRSDS: false, imports: [], debugInfoType: 'dwarf' }`
- **No rebuild (L222–240)**: `needsRebuild=false` → resolves binary path as `<root>/target/debug/<bin>[.exe]`, `buildCargoProject` not called.
- **With rebuild (L242–267)**: `needsRebuild=true`, cargo `release: true` → `buildCargoProject` called with `('/workspace/project', dependencies.logger, 'release')`, result `program` is the built path.
- **Build failure (L269–284)**: `buildCargoProject` returns `{ success: false, error: 'compile error' }` → throws `'Cargo build failed: compile error'`.

### `validateToolchain` (L287–328)
- **MSVC incompatibility (L288–304)**: `detectBinaryFormat` returns msvc format; after `transformLaunchConfig`, `consumeLastToolchainValidation()` returns `{ compatible: false, toolchain: 'msvc', message: contains('MSVC toolchain'), suggestions.length > 0 }`; second call returns `undefined` (consumed).
- **Detection failure fallback (L306–311)**: `detectBinaryFormat` rejects → `validateToolchain` returns `{ compatible: true, toolchain: 'unknown' }`.
- **MSVC behavior error (L313–327)**: `RUST_MSVC_BEHAVIOR=error` → `transformLaunchConfig` throws `AdapterError`.

### DAP operations (L330–396)
- **Invalid exception filters (L331–339)**: `sendDapRequest('setExceptionBreakpoints', { filters: ['unknown'] })` → returns `{}`, warns with `'Unknown exception filters'`.
- **Event handling and state transitions (L342–363)**:
  - `connect()` → state `CONNECTED`
  - `handleDapEvent({ event: 'stopped', body: { threadId: 21 } })` → state `DEBUGGING`, `getCurrentThreadId()===21`, `stopped` event emitted
  - `handleDapEvent({ event: 'terminated' })` → state `CONNECTED`, `getCurrentThreadId()===null`, `terminated` emitted
- **DAP error logging (L365–378)**: `handleDapResponse` with `success: false` → `logger.error` called with `'DAP error'`.
- **Connection lifecycle (L380–395)**: `connect` → `isConnected()=true`, state `CONNECTED`; `disconnect` → `isConnected()=false`, state `DISCONNECTED`.

### Dependency/path utilities (L398–492)
- **Required dependencies (L399–408)**: Expects `CodeLLDB` (installCommand `'npm run build:adapter'`), `Rust`, `Cargo`.
- **Search paths (L410–433)**: Linux adapter: includes `~/.cargo/bin`, `~/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin`, PATH entries. Win32 adapter: includes `Cargo` and `Program Files` paths.
- **Python env scrubbing (L435–465)**: Creates real temp dir; calls private `configurePythonEnvironment(env, adapterPath)`. Verifies PATH includes `adapterDir`, `adapterScripts`, `lldbBin`; `PYTHONHOME` deleted.
- **Space sanitization (L467–486)**: Win32; calls private `prepareCodelldbExecutablePath`; path with spaces → returns path containing `'debug-mcp-codelldb'`, file exists on disk.
- **Adapter metadata (L488–491)**: `getAdapterModuleName()='codelldb'`, `getAdapterInstallCommand()='npm run build:adapter'`.

### Messaging/capabilities (L494–540)
- **Installation guidance (L495–498)**: `getInstallationInstructions()` contains `'Install Rust toolchain'`; `getMissingExecutableError()` contains `'Rust toolchain not found'`.
- **Error translation (L500–513)**: Maps raw error messages to user-friendly strings across 6 cases.
- **Feature support (L516–528)**: `CONDITIONAL_BREAKPOINTS=true`, `REVERSE_DEBUGGING=false`; `DATA_BREAKPOINTS` req type `'version'`; `DISASSEMBLE_REQUEST` req type `'configuration'`; `LOG_POINTS` description contains `'CodeLLDB'`.
- **Default launch config / capabilities (L530–539)**: `defaults.cwd=process.cwd()`, `stopOnEntry=false`; `supportsConditionalBreakpoints=true`, `supportsDisassembleRequest=true`, `supportsSetExpression=false`.

## Key Patterns
- Uses `vi.mocked(fn).mockReset()` in `beforeEach` (instead of relying solely on `vi.clearAllMocks()`) for explicit per-mock reset of each utility.
- Accesses private methods (`configurePythonEnvironment`, `prepareCodelldbExecutablePath`, `resolveCodeLLDBExecutableSync`) via `as unknown as { method: ... }` type casting.
- Directly mutates private field `dlltoolPath` via type cast (L190).
- Real filesystem operations (temp dirs) used for path-sensitive tests (L115–120, L436–465, L469–486).
- `vi.stubEnv` used for all environment variable simulation; cleaned between tests via `beforeEach`.
- `AdapterState` enum values from `@debugmcp/shared` used to verify state machine transitions.
