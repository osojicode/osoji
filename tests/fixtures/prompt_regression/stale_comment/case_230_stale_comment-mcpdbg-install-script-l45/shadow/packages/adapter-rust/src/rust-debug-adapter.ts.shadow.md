# packages\adapter-rust\src\rust-debug-adapter.ts
@source-hash: 5fb7e02f2ccffc2c
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:59Z

## Rust Debug Adapter (`rust-debug-adapter.ts`)

### Purpose
Implements `IDebugAdapter` for Rust via CodeLLDB. Operates in a proxy-based architecture: this class handles configuration, validation, and launch-config transformation, while `ProxyManager` (external) owns actual process spawning and DAP socket communication.

---

### Exported Types

- **`MsvcBehavior`** (L50) — `'warn' | 'error' | 'continue'`; controls response to MSVC-compiled binaries.
- **`ToolchainValidationResult`** (L52–59) — result of binary toolchain detection: `compatible`, `toolchain` ('msvc'|'gnu'|'unknown'), `message`, `suggestions`, `behavior`, `binaryInfo`.

---

### Class: `RustDebugAdapter` (L96–1171)
Extends `EventEmitter`, implements `IDebugAdapter`.

**Key fields:**
- `language = DebugLanguage.RUST` (L97)
- `state: AdapterState` (L100) — internal FSM state
- `msvcBehavior: MsvcBehavior` (L103) — resolved from env `RUST_MSVC_BEHAVIOR`
- `autoSuggestGnu: boolean` (L104) — resolved from env `RUST_AUTO_SUGGEST_GNU`
- `dlltoolPath: string | undefined` (L105) — Windows: path to dlltool.exe
- `executablePathCache: Map<string, ExecutablePathCacheEntry>` (L108) — 60-second TTL cache
- `platform: NodeJS.Platform` (L118) — injectable for tests (issue #186)

---

### Constructor (L115–124)
Accepts `AdapterDependencies` and optional `platform`. Calls `resolveMsvcBehavior()` and `resolveAutoSuggestGnu()` immediately.

---

### Lifecycle

| Method | Lines | Notes |
|--------|-------|-------|
| `initialize()` | L134–162 | Calls `validateEnvironment()`, transitions to READY or ERROR |
| `dispose()` | L164–170 | Clears cache, resets state to UNINITIALIZED |

---

### State Management

| Method | Lines | Notes |
|--------|-------|-------|
| `getState()` | L174–176 | Returns current `AdapterState` |
| `isReady()` | L178–182 | True when READY, CONNECTED, or DEBUGGING |
| `getCurrentThreadId()` | L184–186 | Returns last stopped thread |
| `transitionTo()` (private) | L188–192 | Emits `'stateChanged'` event |

---

### Environment Validation: `validateEnvironment()` (L196–283)
Checks:
1. CodeLLDB executable via `resolveCodeLLDBExecutable()` (async util) — error if missing
2. Rust installation via `checkRustInstallation()` — warning if missing
3. Host triple via `getRustHostTriple()` — warns on `*-pc-windows-msvc`
4. On win32: `findDlltoolExecutable()` — warns if GNU signals present but dlltool absent
5. Cargo via `checkCargoInstallation()` — warning if missing
6. On win32: checks `VCINSTALLDIR`/`VS140COMNTOOLS` — warning if absent

Returns `{ valid: errors.length === 0, errors, warnings }`.

---

### Toolchain Validation

| Method | Lines | Notes |
|--------|-------|-------|
| `validateToolchain(binaryPath)` | L584–636 | Calls `detectBinaryFormat()`, returns `ToolchainValidationResult`; MSVC → incompatible |
| `evaluateToolchain(binaryPath)` (private) | L638–654 | Calls `validateToolchain`, stores result in `lastToolchainValidation`, throws/warns per `msvcBehavior` |
| `consumeLastToolchainValidation()` | L126–130 | Pop-and-return pattern for the cached toolchain validation |
| `buildMsvcWarningMessage(binaryPath)` (private) | L557–582 | Formats multiline MSVC limitation/guidance message |

---

### Executable Resolution

| Method | Lines | Notes |
|--------|-------|-------|
| `resolveExecutablePath(preferredPath?)` | L310–366 | Async; checks cache, validates user path or finds cargo/rustc; relaxed mode allows container/prebuilt fallback |
| `resolveCodeLLDBExecutableSync()` (private) | L729–777 | Synchronous; tries 3 candidate paths by platform/arch, falls back to `CODELLDB_PATH` env |
| `getRelaxedToolchainMode()` (private) | L368–392 | Returns enabled/reason/placeholder based on `MCP_RUST_ALLOW_PREBUILT` or `MCP_CONTAINER` env |
| `getExecutableSearchPaths()` | L398–433 | Platform-aware list of Rust/Cargo bin dirs + PATH |
| `getDefaultExecutableName()` | L394–396 | Returns `'cargo'` |

---

### Adapter Command Building: `buildAdapterCommand(config)` (L658–727)
1. Calls `resolveCodeLLDBExecutableSync()` — throws if not found
2. Calls `prepareCodelldbExecutablePath()` — on win32 with spaces, symlinks to temp dir
3. Validates `config.adapterPort` non-zero
4. Builds args: `['--port', <port>]`, optionally `['--liblldb', <path>]`
5. Prepares env: spreads `process.env`, on win32 sets `LLDB_USE_NATIVE_PDB_READER=1` and `DLLTOOL` env/PATH
6. Calls `configurePythonEnvironment()` to scrub/prepend Python-related env vars
7. Sets `RUST_BACKTRACE=1` if unset
8. Returns `{ command, args, env }`

**`prepareCodelldbExecutablePath(originalPath)` (private, L514–555):** On win32 with spaces in path, copies the entire platform dir to `os.tmpdir()/debug-mcp-codelldb/<platformDir>` (version-checked via `version.json`). Returns sanitized path or original.

**`configurePythonEnvironment(env, adapterPath)` (private, L466–512):** Resolves `lldb` root relative to adapter binary, scrubs `PYTHONHOME`/`PYTHONPATH`/`CODELLDB_STARTUP`, prepends lldb bin/DLLs dirs to `PATH`.

---

### Launch Config Transformation: `transformLaunchConfig(config)` (L789–919)
Produces a `RustLaunchConfig` with `type: 'lldb'`. Three branches for program resolution:
1. **`program` ending in `.rs`**: dynamically imports `cargo-utils.js`, finds Cargo root, resolves binary path, rebuilds if stale via `buildCargoProject`.
2. **`program` (binary path)**: resolves as absolute path relative to cwd.
3. **`cargo` config only**: constructs binary path from `cargo.bin`/`cargo.example`/`cargo.test` or `getDefaultBinary()`.

Throws `AdapterError(SCRIPT_NOT_FOUND)` if neither `program` nor `cargo` provided.

After program resolution, calls `evaluateToolchain(launchConfig.program)` (stores toolchain result).

Always sets `sourceLanguages: ['rust']` for CodeLLDB pretty-printing.

---

### DAP Protocol Stubs

| Method | Lines | Notes |
|--------|-------|-------|
| `sendDapRequest()` | L932–954 | Stub — returns `{}`. Only validates `setExceptionBreakpoints` filter names (`rust_panic`, `cpp_throw`, `cpp_catch`) |
| `handleDapEvent(event)` | L956–975 | Updates `currentThreadId` on `stopped`, transitions state on `terminated`/`exited`, re-emits event |
| `handleDapResponse(response)` | L977–984 | Logs result/error |

---

### Connection Management

| Method | Lines | Notes |
|--------|-------|-------|
| `connect(host, port)` | L988–996 | Sets `connected=true`, transitions to CONNECTED |
| `disconnect()` | L998–1003 | Clears thread, transitions to DISCONNECTED |
| `isConnected()` | L1005–1007 | Returns `this.connected` |

---

### Capabilities & Features

- `supportsFeature(feature)` (L1081–1097): Supported set includes conditional/function/data breakpoints, variable paging, evaluate-for-hovers, set-variable, log points, disassemble, step-in-targets, loaded-sources, terminate.
- `getCapabilities()` (L1131–1170): Full `AdapterCapabilities` object — notably: `supportsStepBack: false`, `supportsExceptionInfoRequest: false` (Rust panics differ from exceptions), `supportsDataBreakpoints: true` (watchpoints).

---

### Environment Variable Contracts (cross-file)
| Variable | Effect |
|----------|--------|
| `RUST_MSVC_BEHAVIOR` | `'warn'` (default) / `'error'` / `'continue'` |
| `RUST_AUTO_SUGGEST_GNU` | `'0'`/`'false'`/`'no'` disables GNU suggestion |
| `MCP_RUST_ALLOW_PREBUILT` | `'true'` enables relaxed toolchain mode |
| `MCP_CONTAINER` | `'true'` enables relaxed toolchain mode |
| `MCP_RUST_EXECUTABLE_PLACEHOLDER` | Override placeholder name in relaxed mode |
| `CODELLDB_PATH` | Fallback path for CodeLLDB executable |
| `CARGO_HOME`, `RUSTUP_HOME` | Used to compute search paths |
| `RUST_BACKTRACE` | Set to `'1'` if not already set |
| `LLDB_USE_NATIVE_PDB_READER` | Set to `'1'` on win32 |
| `DLLTOOL` | Set to discovered dlltool.exe path on win32 |

---

### Architectural Notes
- `sendDapRequest` is a deliberate stub — actual DAP forwarding is done by `ProxyManager`.
- `connect()` does not establish a real TCP connection — that is also owned by `ProxyManager`.
- Toolchain validation result is stored as a one-shot field (`lastToolchainValidation`) to be consumed externally via `consumeLastToolchainValidation()`.
- `resolveCodeLLDBExecutableSync()` duplicates logic from `resolveCodeLLDBExecutable()` in `codelldb-resolver.js` to avoid async in `buildAdapterCommand`.
- `prepareCodelldbExecutablePath` handles Windows paths with spaces by copying to temp dir — version-locked via `version.json` comparison to avoid redundant copies.
