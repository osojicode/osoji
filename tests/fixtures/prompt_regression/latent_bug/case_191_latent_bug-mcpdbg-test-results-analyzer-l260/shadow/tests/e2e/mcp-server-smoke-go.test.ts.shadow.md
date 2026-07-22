# tests\e2e\mcp-server-smoke-go.test.ts
@source-hash: ebfd91c12c4b3c26
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:41Z

## Go Adapter Smoke Tests via MCP Interface

End-to-end smoke test suite validating Go debugging functionality through the MCP (Model Context Protocol) server interface. Spawns a real MCP server subprocess and exercises the Go debug adapter via MCP tool calls.

### Test Suite Structure

**Suite:** `MCP Server Go Debugging Smoke Test @requires-go` (L27-267)

Lifecycle:
- `beforeAll` (L32-55, 30s timeout): Spawns MCP server via `StdioClientTransport` using `dist/index.js --log-level info`, connects an MCP client named `go-smoke-test-client`.
- `afterAll` (L57-76): Closes debug session if open, closes MCP client and transport.
- `afterEach` (L78-88): Closes and nullifies `sessionId` after each test.

### Test Cases

1. **`should create Go debug session through MCP interface`** (L90-108)
   - Calls `create_debug_session` with `language: 'go'`, `name: 'go-smoke-test'`
   - Validates `sessionId` is defined and truthy
   - Implicitly validates Go adapter registration in `AdapterLoader`

2. **`should list Go adapter in supported languages`** (L110-139)
   - Calls `list_supported_languages` with no arguments
   - Handles two response shapes: `adapters` array or `languages` array (items may be strings or objects with `name`/`id`)
   - Searches for adapter where `name === 'go'` or `id === 'go'`
   - If neither array shape is present, logs and passes (lenient smoke test)

3. **`should complete Go debugging flow with compiled binary`** (L141-266, 60s timeout)
   - Pre-flight: checks `go version` and `dlv version` via `execSync`; skips gracefully if either unavailable
   - Compiles `examples/go/hello_world.go` with debug symbols (`-gcflags="all=-N -l"`) to `examples/go/hello_world_test`
   - Full flow: create session → set breakpoint at line 12 → start debugging (binary exec mode, no explicit `mode` arg) → wait 1s → get stack trace → continue execution → wait 1s
   - Uses `skipIfSpawnBlocked` (L231) to conditionally skip (not hard-fail) if Delve cannot be spawned
   - `finally` block deletes compiled test binary

### Key Patterns

- **MCP tool invocation:** Direct `mcpClient!.callTool({name, arguments})` (L93, L115, L184, L199, L216) vs. `callToolSafely` wrapper for non-critical calls (L241, L250)
- **Result parsing:** All responses parsed through `parseSdkToolResult` before assertion
- **Graceful degradation:** Tests that require Go/Delve return early rather than fail hard when toolchain unavailable
- **Mode inference under test (L211-214):** The binary exec test intentionally omits `mode` to validate the adapter's auto-inference from file extension absence

### Path Resolution

- `__dirname` derived via `fileURLToPath(import.meta.url)` (L23-24) for ESM compatibility
- `ROOT` = two levels up from `tests/e2e/` = project root (L25)
- Test binary: `ROOT/examples/go/hello_world_test` (L168)
- MCP server: `ROOT/dist/index.js` (L38)

### Dependencies

- `@modelcontextprotocol/sdk`: `Client`, `StdioClientTransport`
- `./smoke-test-utils.js`: `parseSdkToolResult`, `callToolSafely`
- `../test-utils/helpers/adapter-spawn.js`: `skipIfSpawnBlocked`