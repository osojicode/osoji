# tests\e2e\mcp-server-smoke-go.test.ts
@source-hash: ebfd91c12c4b3c26
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:31Z

## Go Adapter Smoke Tests via MCP Interface

End-to-end smoke test suite validating Go debugging functionality through the MCP (Model Context Protocol) server interface. Tests cover adapter registration, session creation, breakpoints, stack traces, and the full debugging flow with a compiled binary using Delve.

### Test Suite: `MCP Server Go Debugging Smoke Test @requires-go` (L27–267)

Tagged `@requires-go` for selective test runs. Uses shared state: `mcpClient`, `transport`, `sessionId` (L28–30).

#### Lifecycle Hooks

- **`beforeAll`** (L32–55, timeout 30s): Spawns MCP server subprocess via `StdioClientTransport` running `dist/index.js --log-level info`, creates and connects an MCP `Client` named `go-smoke-test-client`.
- **`afterAll`** (L57–76): Closes session (if open), then closes MCP client and transport.
- **`afterEach`** (L78–88): Closes and nulls `sessionId` after each test to prevent leak between tests.

#### Test Cases

1. **`should create Go debug session through MCP interface`** (L90–108)
   - Calls `create_debug_session` MCP tool with `language: 'go'`, `name: 'go-smoke-test'`
   - Validates `sessionId` is defined and truthy
   - Primary integration point check: verifies Go adapter is registered in `AdapterLoader`

2. **`should list Go adapter in supported languages`** (L110–139)
   - Calls `list_supported_languages` MCP tool
   - Handles both `adapters` and `languages` response shapes (L122–124)
   - Searches for `'go'` by string value, `.name`, or `.id` (L126–128)
   - Soft-passes if response format is unexpected (L131–134)

3. **`should complete Go debugging flow with compiled binary`** (L141–266, timeout 60s)
   - **Prerequisite checks**: Detects `go` and `dlv` availability via `execSync` (L143–164); returns early if either is missing
   - **Binary compilation**: Builds `examples/go/hello_world.go` with debug symbols (`-gcflags="all=-N -l"`) to `examples/go/hello_world_test` (L167–179)
   - **Full flow** (L181–254):
     1. `create_debug_session` with `language: 'go'`
     2. `set_breakpoint` at line 12 of the Go file
     3. `start_debugging` with pre-compiled binary (no explicit `mode`; adapter must auto-infer `exec` from absent `.go` extension — this is the explicit property under test, L211–214)
     4. Uses `skipIfSpawnBlocked` helper if Delve spawn fails (L231)
     5. `get_stack_trace` (soft check, logs frame count)
     6. `continue_execution`
   - **Cleanup** (L255–264): Removes compiled binary using dynamic `fs` import

### Key Architectural Decisions

- MCP server is spawned as a child process; communication is via stdio transport — tests exercise the full server stack, not mocked adapters.
- `parseSdkToolResult` and `callToolSafely` (from `smoke-test-utils.js`) normalize MCP SDK responses.
- `skipIfSpawnBlocked` (from `adapter-spawn.js`) allows graceful skip instead of failure when OS blocks process spawning.
- The test file sets up `__dirname`/`__filename` ESM shims (L23–25) and resolves paths relative to repo root (L25).
- `NODE_ENV: 'test'` is injected into the server environment (L41).
- The full debugging flow test uses a 60s timeout (L266) to accommodate `go build` + Delve startup latency.

### Notable Path References

- MCP server entry: `dist/index.js` (relative to repo root)
- Go test source: `examples/go/hello_world.go`
- Compiled test binary: `examples/go/hello_world_test` (ephemeral, deleted in finally block)
