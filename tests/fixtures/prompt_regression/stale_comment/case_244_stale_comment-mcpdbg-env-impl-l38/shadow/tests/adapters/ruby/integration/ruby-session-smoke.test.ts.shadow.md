# tests\adapters\ruby\integration\ruby-session-smoke.test.ts
@source-hash: 1aba52f4a22f53ea
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:23Z

## Ruby Session Smoke Integration Tests

Integration smoke tests for the Ruby debug adapter (`@debugmcp/adapter-ruby`), validating the core behaviors of `RubyAdapterFactory` and its produced adapter without requiring a real Ruby toolchain.

### Purpose
Exercises the public API surface of the Ruby adapter — command building, launch/attach config transformation, metadata, and dependency reporting — using a stub `AdapterDependencies` implementation and `process.execPath` as a fake `rdbg` binary.

---

### Key Fixtures

**`createDependencies()` (L7–36)**  
Factory returning a no-op `AdapterDependencies` stub:
- `fileSystem`: All methods are no-ops or return empty/false values; `stat` returns `{} as Stats`.
- `logger`: All four log methods (`info`, `error`, `debug`, `warn`) are no-ops.
- `environment`: Delegates `get` to `process.env[key]`, `getAll` to a shallow copy of `process.env`, `getCurrentWorkingDirectory` to `process.cwd()`.

**Suite-level constants (L39–46)**
- `adapterPort = 48767` — fixed TCP port for DAP.
- `sessionId = 'session-ruby-smoke'` — stable session identifier.
- `adapterHost = '127.0.0.1'`
- `fakeLogDir` — `<cwd>/logs/tests`
- `sampleScriptPath` — `<cwd>/examples/ruby/fizzbuzz.rb`
- `fakeRdbgPath = process.execPath` — uses Node binary as stand-in for `rdbg` so invocation construction is exercised without a real Ruby install.

**`RDBG_PATH` env management (L48–61)**  
`beforeEach` saves and overrides `RDBG_PATH` with `fakeRdbgPath`; `afterEach` restores or deletes it to avoid cross-test pollution.

---

### Test Cases

#### `builds an rdbg command that stops at load and serves DAP over TCP` (L63–90)
Creates adapter via `factory.createAdapter(createDependencies())`, calls `adapter.buildAdapterCommand(...)` with a cast-to-`never` options object (bypasses strict typing), then asserts on `command.args`:
- Contains `--open`, `--host`, and the port string.
- Does **not** contain `--nonstop` (stop-at-load is mandatory so the proxy can connect before short scripts finish).
- No arg contains `vscode` (prevents launching editor frontend mode).
- `-c` flag is present and is followed by `['--', 'ruby', sampleScriptPath]` (command mode: rdbg runs `ruby <script>` under debugger).

#### `normalizes launch config for Ruby scripts` (L92–106)
Calls `adapter.transformLaunchConfig({ program, stopOnEntry: true, justMyCode: false })` (async). Asserts result has `type: 'rdbg'`, `request: 'launch'`, `script === sampleScriptPath`, `stopOnEntry === true`.

#### `transforms attach config with discrete host and port` (L108–127)
Calls `adapter.transformAttachConfig!({ request: 'attach', host, port: 12345, stopOnEntry: true })`. Asserts result matches `{ type: 'rdbg', request: 'attach', host: '127.0.0.1', port: 12345, localfs: true }`. Also asserts `adapter.usesDirectConnectForAttach?.()` returns `true`.

#### `returns correct metadata from factory` (L129–136)
Calls `factory.getMetadata()`. Asserts `displayName === 'Ruby'`, `.rb` is in `fileExtensions`, `description` contains `'rdbg'`.

#### `returns required dependencies and install instructions` (L138–149)
Calls `adapter.getRequiredDependencies()` — expects entries with `name === 'Ruby'` and a name including `'debug gem'`. Calls `adapter.getInstallationInstructions()` — expects `'gem install debug'` and `'ruby-lang.org'` substrings.

---

### Architectural Notes
- Uses `as never` casts (L76, L100) to pass partial/incompatible config shapes through strict adapter APIs without TypeScript errors, accepting runtime risk in a test context.
- Optional-chaining `?.` on `transformAttachConfig` (L112) and `usesDirectConnectForAttach` (L126) matches adapters that may not implement optional interface members.
- No actual process spawning or network I/O occurs; all adapter behavior under test is pure construction/transformation logic.
- The `RDBG_PATH` environment variable is the cross-cutting concern linking test setup to the adapter's command-building logic.
