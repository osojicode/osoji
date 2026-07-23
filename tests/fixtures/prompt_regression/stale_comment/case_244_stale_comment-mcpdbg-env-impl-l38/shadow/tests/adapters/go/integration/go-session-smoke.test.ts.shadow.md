# tests\adapters\go\integration\go-session-smoke.test.ts
@source-hash: 127f00f5fa5ae820
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:36Z

## Go Adapter Session Smoke Tests (Integration)

Integration smoke tests for the Go debugger adapter (`@debugmcp/adapter-go`). Validates the `GoAdapterFactory` and its produced adapter across command building, launch config normalization, test mode support, metadata, dependency declarations, and installation instructions — without launching an actual Delve process.

### Test Setup (L8–60)

**`createDependencies()` (L8–37):** Factory function returning a no-op `AdapterDependencies` stub:
- `fileSystem`: All methods are stubs; `exists`/`pathExists`/`existsSync` always return `false`/`[]`.
- `logger`: All log methods are silent no-ops.
- `environment`: Delegates `get`/`getAll` to live `process.env`; `getCurrentWorkingDirectory` returns `process.cwd()`.

**Global constants (L40–45):**
- `adapterPort = 48766` — TCP port used in command-build assertions.
- `sessionId = 'session-go-smoke'`
- `adapterHost = '127.0.0.1'`
- `fakeLogDir` — `<cwd>/logs/tests`
- `sampleScriptPath` — `<cwd>/examples/go/main.go`
- `fakeDlvPath = process.execPath` — Node.js binary substituted for `dlv` so `existsSync` passes on any machine.

**`DLV_PATH` env management (L47–60):**
- `beforeEach`: saves `process.env.DLV_PATH`, sets it to `fakeDlvPath`.
- `afterEach`: restores original value or deletes key if it was undefined.

### Test Cases

| Test | Lines | What is verified |
|------|-------|-----------------|
| `builds dlv dap command with TCP port` | L62–81 | `buildAdapterCommand` returns an absolute, existent command path; `args` includes `'dap'` and `--listen=127.0.0.1:48766`. |
| `normalizes launch config for Go programs` | L83–101 | `transformLaunchConfig` sets `type='go'`, `request='launch'`, `mode='debug'`, and preserves `program`, `cwd`, `args`. |
| `handles test mode configuration` | L103–118 | `transformLaunchConfig` with `mode:'test'` preserves `mode='test'` and keeps `args` like `-test.v`. |
| `returns correct metadata from factory` | L120–127 | `factory.getMetadata()` returns `displayName='Go'`, `.go` in `fileExtensions`, `'Delve'` in `description`. |
| `returns required dependencies` | L129–137 | `adapter.getRequiredDependencies()` has exactly 2 entries: one named `'Go'`, one containing `'Delve'`. |
| `provides installation instructions` | L139–147 | `adapter.getInstallationInstructions()` mentions `'go.dev'`, `'delve'`, `'go install'`. |

### Architecture Notes
- Uses `GoAdapterFactory` (not a singleton); each test instantiates a fresh factory and adapter to ensure isolation.
- `fakeDlvPath = process.execPath` is the core trick: using the Node.js binary as a stand-in for `dlv` makes `existsSync(command.command)` pass without requiring Delve to be installed.
- All tests cast configs with `as any` to bypass TypeScript strictness on incomplete launch config shapes.
- No real filesystem I/O or network connections are made; this is a "smoke" test verifying the adapter's configuration logic.