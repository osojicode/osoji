# tests\adapters\go\integration\go-session-smoke.test.ts
@source-hash: 127f00f5fa5ae820
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:25Z

## Go Adapter Session Smoke Tests (Integration)

Integration smoke tests for the Go debug adapter (`@debugmcp/adapter-go`), validating end-to-end behavior of `GoAdapterFactory` and the adapter it produces. Tests focus on command construction, launch config transformation, metadata, dependencies, and installation instructions.

### Test Suite: `Go adapter - session smoke (integration)` (L39–148)

**Setup/Teardown:**
- `beforeEach` (L49–52): Saves `process.env.DLV_PATH` and replaces it with `process.execPath` (the current Node.js binary, acting as a fake `dlv` executable).
- `afterEach` (L54–60): Restores original `DLV_PATH` or deletes the key if it was previously undefined.

### Helper: `createDependencies()` (L8–37)
Returns a stub `AdapterDependencies` object with no-op implementations for:
- `fileSystem`: All methods return empty/false/no-op values; `environment.get` delegates to `process.env`.
- `logger`: All log methods are no-ops.
- `environment`: Reads from `process.env`, `process.cwd()`.

### Test Cases

| Test | Line | What it asserts |
|------|------|-----------------|
| `builds dlv dap command with TCP port` | L62–81 | `buildAdapterCommand` returns a command with an absolute, existing path; args include `'dap'` and `--listen=127.0.0.1:48766` |
| `normalizes launch config for Go programs` | L83–101 | `transformLaunchConfig` sets `type='go'`, `request='launch'`, `mode='debug'`, preserves `program`, `cwd`, `args` |
| `handles test mode configuration` | L103–118 | `transformLaunchConfig` with `mode='test'` preserves `mode='test'` and passes through test args |
| `returns correct metadata from factory` | L120–127 | `factory.getMetadata()` has `displayName='Go'`, `.go` extension, description containing `'Delve'` |
| `returns required dependencies` | L129–137 | `adapter.getRequiredDependencies()` returns exactly 2 deps: one named `'Go'`, one whose name includes `'Delve'` |
| `provides installation instructions` | L139–147 | `adapter.getInstallationInstructions()` mentions `'go.dev'`, `'delve'`, `'go install'` |

### Key Constants
- `adapterPort = 48766` (L40): TCP port used for DAP listener assertion.
- `sessionId = 'session-go-smoke'` (L41)
- `adapterHost = '127.0.0.1'` (L42)
- `fakeDlvPath = process.execPath` (L45): Node.js binary substituted as fake `dlv` path; allows `existsSync` check to pass (L78).
- `sampleScriptPath`: `<cwd>/examples/go/main.go` (L44) — path need not exist for most tests.

### Dependencies
- `@debugmcp/adapter-go`: `GoAdapterFactory` — the primary SUT.
- `@debugmcp/shared`: `AdapterDependencies` type — interface for injected dependencies.
- `vitest`: Test runner.
- `path`, `fs.existsSync`: Node stdlib used for path/file assertions.