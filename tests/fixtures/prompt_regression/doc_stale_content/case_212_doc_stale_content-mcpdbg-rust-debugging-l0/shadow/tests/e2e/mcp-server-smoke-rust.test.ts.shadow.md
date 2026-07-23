# tests\e2e\mcp-server-smoke-rust.test.ts
@source-hash: 78616b81db972069
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:08Z

## Rust Adapter Smoke Test via MCP Interface

End-to-end smoke test suite validating the Rust debugging adapter through the MCP (Model Context Protocol) server interface. Tests real DAP-based debugging of compiled Rust binaries using CodeLLDB, exercising the full stack from MCP client → MCP server → DAP proxy → CodeLLDB.

### Test Structure

**Suite:** `MCP Server Rust Debugging Smoke Test` (L17–326)

**Lifecycle:**
- `beforeAll` (L22–44): Validates `dist/index.js` exists, spawns MCP server via `StdioClientTransport`, connects `Client`. Timeout: 30s.
- `afterEach` (L46–51): Closes any open debug session via `close_debug_session` tool call.
- `afterAll` (L53–62): Closes MCP client and transport.

### Test Cases

**Test 1:** `starts Rust debug session end-to-end without proxy exit` (L64–196, timeout 60s)
- Prepares `hello_world` Rust example via `prepareRustExample('hello_world')` (L67–68)
- Flow: `create_debug_session` → `set_breakpoint` (line 26 in hello_world src) → `start_debugging` (stopOnEntry, rust sourceLanguages) → poll stack trace for user frame in `/examples/rust/hello_world/src/` → `get_local_variables`
- Assertions: `name` local variable has value `"Rust"` (via regex on quoted string); `version` local contains `'1.75'` if present (L186–193)
- Skip logic: calls `skipIfSpawnBlocked` if CodeLLDB binary fails to spawn (L112)

**Test 2:** `steps through async await and inspects locals` (L198–325, timeout 60s)
- Prepares `async_example` Rust example via `prepareRustExample('async_example')` (L201–202)
- Flow: `create_debug_session` → `set_breakpoint` (line 46 in async_example src) → `start_debugging` (stopOnEntry) → poll for user frame in `/examples/rust/async_example/src/` → `get_local_variables` → `continue_execution`
- Assertions: `id` local equals `'1'`; `result` local contains `'Data_1'` if present; final continue succeeds
- Skip logic: calls `skipIfSpawnBlocked` if CodeLLDB unavailable (L243)

### Key Patterns

**Stack Polling Pattern** (both tests): After initial 500ms wait, checks stack frames for user code. If not found, calls `continue_execution` and polls up to 10 times × 300ms to reach the user breakpoint. Handles `stopOnEntry` at runtime entry point before user code.

**User Frame Detection:** `isUserFrame` / `isAsyncUserFrame` helpers normalize backslashes and check for project-relative path inclusion (L133–137, L262–266).

**Error Handling:** `parseSdkToolResult` unwraps MCP tool responses; `callToolSafely` used in cleanup. Non-success responses throw descriptive errors with full JSON. Environmental failures (Windows Smart App Control blocking CodeLLDB spawn) are handled via `skipIfSpawnBlocked` rather than hard-failing.

### Module-Level Constants

- `ROOT` (L16): resolved path two levels above `__dirname` (project root)
- `distEntry` (L23): `<ROOT>/dist/index.js` — required build artifact

### MCP Tools Exercised

- `create_debug_session` — creates a Rust debug session
- `set_breakpoint` — sets file/line breakpoint
- `start_debugging` — launches binary with DAP config
- `get_stack_trace` — fetches current stack frames
- `continue_execution` — resumes execution
- `get_local_variables` — reads locals at current frame
- `close_debug_session` — cleanup in afterEach
