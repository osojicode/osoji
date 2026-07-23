# tests\adapters\rust\integration\rust-session-smoke.test.ts
@source-hash: f81ee156d32cbdcd
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:37Z

## Purpose
Integration smoke tests for the Rust adapter's session lifecycle — specifically `buildAdapterCommand` and `transformLaunchConfig` — without spawning real processes or requiring actual CodeLLDB installation.

## Test Suite: `Rust adapter - session smoke (integration)` (L39–121)

### Test Configuration Constants (L40–45)
- `adapterPort = 48765` — fixed TCP port used for adapter command construction
- `sessionId = 'session-rust-smoke'` — synthetic session identifier
- `adapterHost = '127.0.0.1'` — loopback host
- `fakeLogDir` — `<cwd>/logs/tests`
- `sampleScriptPath` — `<cwd>/examples/rust/src/main.rs`
- `fakeCodelldbPath = process.execPath` — uses the Node.js binary as a fake CodeLLDB executable (guaranteed to exist and be absolute)

### Environment Setup (L50–69)
- `beforeEach` (L50–55): Saves and overrides `CODELLDB_PATH` (set to Node binary path) and deletes `RUST_BACKTRACE` to ensure clean defaults.
- `afterEach` (L57–69): Restores both env vars precisely — distinguishes `undefined` (was never set, delete it) vs `string` (was set, restore it).

### `createDependencies()` (L8–37)
Factory returning a stub `AdapterDependencies` object:
- `fileSystem`: all no-ops; `exists`/`pathExists`/`existsSync` return false/false/false; `stat` returns empty object cast as `fs.Stats`
- `logger`: all methods are silent no-ops
- `environment`: proxies to real `process.env` and `process.cwd()` — this is intentional so the test can manipulate env vars and have the adapter see them

### Test 1: `builds CodeLLDB command with TCP port and Rust env defaults` (L71–99)
Exercises `adapter.buildAdapterCommand(...)` with `as any` cast (L84):
- Asserts `command.command` is an absolute path that physically exists on disk (L86–87) — relies on `fakeCodelldbPath = process.execPath`
- Asserts first two args are `['--port', '48765']` (L88–89)
- If additional args exist, asserts `--liblldb` is among them (L90–92) — optional guard
- Asserts `RUST_BACKTRACE` env is `'1'` (L93) — verifies Rust env defaults injection
- Platform-conditional check (L94–98): on `win32`, `LLDB_USE_NATIVE_PDB_READER` must be `'1'`; on others, must be `undefined`

### Test 2: `normalizes binary launch config for existing Rust artifacts` (L101–120)
Exercises `adapter.transformLaunchConfig(...)` with a binary launch config:
- `program`: relative path `target/debug/<binaryName>` (platform-aware: `.exe` on Windows)
- Asserts output `type` is `'lldb'` (L114)
- Asserts `program` is resolved to absolute path via `path.resolve(projectRoot, ...)` (L115)
- Asserts `cwd` passthrough (L116)
- Asserts `args` passthrough (L117)
- Asserts `sourceLanguages` defaults to `['rust']` (L118)
- Asserts `console` defaults to `'internalConsole'` (L119)

## Key Architectural Decisions
- Tests use `as any` casts (L84, L112) to avoid fully satisfying adapter option type signatures, reducing test boilerplate.
- `fakeCodelldbPath = process.execPath` is a clever trick: it provides a real, existing absolute path without requiring CodeLLDB installed.
- `environment.get` proxies to real `process.env` (L33), so env var mutations in `beforeEach`/`afterEach` are visible to the adapter under test.
- No real processes are spawned; this tests only the command/config construction logic.

## Dependencies
- `RustAdapterFactory` from `../../../../packages/adapter-rust/src/index.js` — the primary subject under test
- `AdapterDependencies` type from `@debugmcp/shared` — defines the stub interface shape
- `vitest` for test infrastructure
- Node built-ins: `path`, `fs.existsSync`
