# packages\adapter-rust\src\rust-debug-adapter.ts
@source-hash: cde554f3f23bacff
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:19Z

## RustDebugAdapter — `packages/adapter-rust/src/rust-debug-adapter.ts`

### Purpose
Implements `IDebugAdapter` for Rust debugging via CodeLLDB. Responsible for environment validation, CodeLLDB process command building, launch config transformation (source→binary resolution), toolchain compatibility checks (MSVC vs GNU), and DAP event/response handling. Actual process spawning and DAP socket communication are delegated to `ProxyManager` (not in this file).

---

### Exported Types

#### `MsvcBehavior` (L50)
Union type `'warn' | 'error' | 'continue'`. Controls how MSVC-compiled binaries are handled. Resolved from env var `RUST_MSVC_BEHAVIOR` (defaults to `'warn'`).

#### `ToolchainValidationResult` (L52–59)
Interface returned by `validateToolchain()`. Fields: `compatible`, `toolchain` (`'msvc'|'gnu'|'unknown'`), `message?`, `suggestions?`, `behavior: MsvcBehavior`, `binaryInfo: BinaryInfo`.

---

### Primary Class: `RustDebugAdapter` (L96–1171)
Extends `EventEmitter`, implements `IDebugAdapter`.

**Key fields:**
- `language = DebugLanguage.RUST` (L97)
- `state: AdapterState` — state machine (L100), transitions: UNINITIALIZED → INITIALIZING → READY/ERROR → CONNECTED → DEBUGGING → DISCONNECTED
- `msvcBehavior: MsvcBehavior` — resolved once in constructor via `resolveMsvcBehavior()` (L122)
- `autoSuggestGnu: boolean` — resolved once via `resolveAutoSuggestGnu()` (L123)
- `dlltoolPath: string | undefined` — set during `validateEnvironment()` on win32 (L239)
- `executablePathCache: Map<string, ExecutablePathCacheEntry>` — 60-second TTL cache for executable paths (L108–109)
- `lastToolchainValidation: ToolchainValidationResult | undefined` — consumed by `consumeLastToolchainValidation()` (L126–130)

---

### Key Methods

#### Lifecycle
- **`initialize()` (L134–162)**: Calls `validateEnvironment()`, emits `'initialized'`, transitions to READY or throws on failure.
- **`dispose()` (L164–170)**: Clears cache, resets state to UNINITIALIZED, emits `'disposed'`.

#### Environment Validation
- **`validateEnvironment()` (L196–283)**: Checks CodeLLDB presence (`resolveCodeLLDBExecutable`), Rust installation, host triple for MSVC toolchain warning, dlltool on win32 GNU targets, Cargo installation, and MSVC runtime on Windows. Returns `ValidationResult`.
- **`getRequiredDependencies()` (L285–306)**: Returns `DependencyInfo[]` for CodeLLDB (required), Rust, and Cargo.

#### Executable Resolution
- **`resolveExecutablePath(preferredPath?)` (L310–366)**: Async; validates preferred path or discovers `cargo`/`rustc`. Supports relaxed mode via `MCP_RUST_ALLOW_PREBUILT` or `MCP_CONTAINER` env vars. Caches results for 60s.
- **`resolveCodeLLDBExecutableSync()` (L729–777)**: Synchronous CodeLLDB discovery checking 3 candidate paths relative to `__dirname`/CWD, then `CODELLDB_PATH` env var. Returns `string | null`.
- **`getExecutableSearchPaths()` (L398–433)**: Platform-specific `$CARGO_HOME/bin`, `$RUSTUP_HOME/toolchains/…/bin`, system paths, and `$PATH`.

#### Adapter Command Building
- **`buildAdapterCommand(config)` (L658–727)**: **Critical path.** Resolves CodeLLDB path synchronously, applies path sanitization for Windows paths with spaces (`prepareCodelldbExecutablePath`), appends `--port` and `--liblldb` args, configures environment (RUST_BACKTRACE, LLDB_USE_NATIVE_PDB_READER on win32, DLLTOOL, Python env). Returns `AdapterCommand`.
- **`prepareCodelldbExecutablePath(originalPath)` (L514–555)**: On win32, copies CodeLLDB to a temp path without spaces (`%TEMP%/debug-mcp-codelldb/…`) if the original path contains spaces; uses `version.json` to determine if copy needs refresh.
- **`configurePythonEnvironment(env, adapterPath)` (L466–512)**: Scrubs `PYTHONHOME`/`PYTHONPATH`/`CODELLDB_STARTUP` and prepends vendored `lldb/bin`, `lldb/DLLs`, and adapter dirs to `PATH`.

#### Launch Config Transformation
- **`transformLaunchConfig(config)` (L789–919)**: Resolves `program` from:
  1. `.rs` source file → dynamically imports `./utils/cargo-utils.js`, finds project root, determines binary, optionally rebuilds via `buildCargoProject`.
  2. Explicit binary path → `path.resolve(cwd, programPath)`.
  3. `cargo` config block → constructs target path from `bin`/`example`/`test`/`'main'`.
  Always calls `evaluateToolchain()` on the resolved binary path before returning.
- **`evaluateToolchain(binaryPath)` (L638–654)**: Internal; calls `validateToolchain()`, stores result in `lastToolchainValidation`, throws `AdapterError` if `behavior === 'error'`, logs warn if `behavior === 'warn'`.
- **`validateToolchain(binaryPath)` (L584–636)**: Public; calls `detectBinaryFormat()` to determine MSVC vs GNU, builds warning message, returns `ToolchainValidationResult`.

#### DAP Protocol
- **`sendDapRequest(command, args?)` (L932–954)**: Stub — only validates `setExceptionBreakpoints` filters against `['rust_panic', 'cpp_throw', 'cpp_catch']`. Returns `{} as T`. Real forwarding done by ProxyManager.
- **`handleDapEvent(event)` (L956–975)**: Updates `currentThreadId` and state machine from `stopped`/`terminated`/`exited` events.
- **`handleDapResponse(response)` (L977–984)**: Logs errors.

#### Connection Management
- **`connect(host, port)` (L988–996)**: Sets `connected = true`, transitions to CONNECTED, emits `'connected'`.
- **`disconnect()` (L998–1003)**: Clears state, transitions to DISCONNECTED.

#### Feature/Capability Declarations
- **`supportsFeature(feature)` (L1081–1097)**: Supports 11 `DebugFeature` values including conditional breakpoints, data breakpoints, disassemble.
- **`getCapabilities()` (L1131–1170)**: Full `AdapterCapabilities` object for CodeLLDB/LLDB.

---

### Architecture Notes
- **Proxy pattern**: This adapter is a configuration/metadata layer. `buildAdapterCommand` produces a command to spawn CodeLLDB; actual spawning and DAP socket communication happen in `ProxyManager`.
- **Windows space-in-path workaround** (L514–555): CodeLLDB may fail when its path contains spaces on Windows; the adapter copies the vendor directory to `os.tmpdir()`.
- **Relaxed toolchain mode** (L368–392): Supports containerized/prebuilt environments via `MCP_RUST_ALLOW_PREBUILT=true` or `MCP_CONTAINER=true`, allowing absence of `cargo`/`rustc` without errors.
- **Dynamic import of `cargo-utils`** (L828–829): `transformLaunchConfig` lazily imports `./utils/cargo-utils.js` only when a `.rs` source file is provided.
- **`consumeLastToolchainValidation()`** (L126–130): Destructive read — callers (likely ProxyManager/session layer) call this after `transformLaunchConfig` to retrieve and clear the stored `ToolchainValidationResult`.

---

### Environment Variables Consumed
- `RUST_MSVC_BEHAVIOR` — `'warn'|'error'|'continue'` (default `'warn'`)
- `RUST_AUTO_SUGGEST_GNU` — `'0'|'false'|'no'` to disable GNU suggestions
- `MCP_RUST_ALLOW_PREBUILT=true` — relaxed toolchain mode
- `MCP_CONTAINER=true` — relaxed toolchain mode
- `MCP_RUST_EXECUTABLE_PLACEHOLDER` — placeholder binary name in relaxed mode
- `CODELLDB_PATH` — override for CodeLLDB executable location
- `RUSTUP_HOME`, `CARGO_HOME`, `HOME` — for search path construction
- `CARGO_BUILD_TARGET`, `RUSTFLAGS`, `RUST_TARGET` — GNU toolchain detection
- `VCINSTALLDIR`, `VS140COMNTOOLS` — MSVC runtime detection on Windows
- `RUST_BACKTRACE` — set to `'1'` if not already present
- `DLLTOOL` — set to discovered `dlltoolPath` on Windows
