# tests\adapters\ruby\integration\ruby-session-smoke.test.ts
@source-hash: 1aba52f4a22f53ea
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## Purpose
Integration smoke tests for the Ruby debug adapter (`@debugmcp/adapter-ruby`). Verifies that `RubyAdapterFactory` and its created adapter correctly build rdbg commands, normalize launch/attach configs, return proper metadata, and report required dependencies — all without requiring an actual Ruby or rdbg toolchain.

## Key Structure

### `createDependencies` (L7–36)
Factory function returning a stub `AdapterDependencies` object with no-op implementations of:
- `fileSystem`: all methods return empty/false/no-op values
- `logger`: all log methods are no-ops
- `environment`: proxies to real `process.env` and `process.cwd()`

This stub is shared across all test cases via inline calls.

### Test Suite: `Ruby adapter - session smoke (integration)` (L38–149)
**Setup/teardown** (L48–61): Saves and restores `RDBG_PATH` env var around each test. Sets `RDBG_PATH = process.execPath` (the Node.js binary) to exercise command construction without a real Ruby installation.

**Constants** (L39–46):
- `adapterPort`: 48767
- `sessionId`: `'session-ruby-smoke'`
- `adapterHost`: `'127.0.0.1'`
- `fakeLogDir`: `<cwd>/logs/tests`
- `sampleScriptPath`: `<cwd>/examples/ruby/fizzbuzz.rb`
- `fakeRdbgPath`: `process.execPath` (Node binary as stand-in for rdbg)

### Test Cases

**`'builds an rdbg command that stops at load and serves DAP over TCP'`** (L63–90)
- Creates factory → adapter → calls `buildAdapterCommand` with launch params (L67–76, cast `as never`)
- Asserts `command.args` contains `--open`, `--host`, port string
- Asserts `--nonstop` is absent (stop-at-load is required so proxy can connect)
- Asserts no `vscode` substring in any arg (avoids editor-launch mode)
- Asserts `-c` flag present and followed by `-- ruby <sampleScriptPath>` (command mode)

**`'normalizes launch config for Ruby scripts'`** (L92–106)
- Calls `adapter.transformLaunchConfig` with `{program, stopOnEntry, justMyCode}` (async, `as never`)
- Asserts `transformed.type === 'rdbg'`, `request === 'launch'`, `script === sampleScriptPath`, `stopOnEntry === true`

**`'transforms attach config with discrete host and port'`** (L108–127)
- Calls `adapter.transformAttachConfig!({request:'attach', host, port, stopOnEntry})`
- Asserts result matches `{type:'rdbg', request:'attach', host:'127.0.0.1', port:12345, localfs:true}`
- Asserts `adapter.usesDirectConnectForAttach?.()` is `true`

**`'returns correct metadata from factory'`** (L129–136)
- Calls `factory.getMetadata()`
- Asserts `displayName === 'Ruby'`, `.rb` in `fileExtensions`, `'rdbg'` in `description`

**`'returns required dependencies and install instructions'`** (L138–149)
- Calls `adapter.getRequiredDependencies()` — asserts entries named `'Ruby'` and one containing `'debug gem'`
- Calls `adapter.getInstallationInstructions()` — asserts contains `'gem install debug'` and `'ruby-lang.org'`

## Key Architectural Decisions
- **No real process spawning**: uses `process.execPath` as `RDBG_PATH` to exercise invocation logic structurally without launching anything
- **`as never` casts** (L76, L100): bypass TypeScript strict typing on config objects to pass partial/mismatched shapes into the adapter API
- **Optional chaining on `transformAttachConfig!` and `usesDirectConnectForAttach?.`** (L112, L126): the `!` asserts non-null for attach config transform while `?.` safely calls optional capability check
- **Env var isolation** (L50–61): proper save/restore pattern ensures `RDBG_PATH` side effects don't leak between tests

## Dependencies
- `vitest`: test framework (describe/it/expect/beforeEach/afterEach)
- `@debugmcp/shared`: `AdapterDependencies` type (interface for filesystem, logger, environment)
- `@debugmcp/adapter-ruby`: `RubyAdapterFactory` — the primary SUT
- `path`, `process`: Node.js builtins for path construction and env manipulation