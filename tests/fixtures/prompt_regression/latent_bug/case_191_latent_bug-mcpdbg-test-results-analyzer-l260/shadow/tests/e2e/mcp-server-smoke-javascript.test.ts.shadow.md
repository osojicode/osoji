# tests\e2e\mcp-server-smoke-javascript.test.ts
@source-hash: c338a93197059f73
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:54Z

## JavaScript MCP Debugger E2E Smoke Tests

End-to-end smoke tests verifying the JavaScript debugging functionality of the MCP debugger server via the MCP client SDK. Tests are intentionally high-level, avoiding coupling to implementation details, focusing on observable behavior correctness.

### Architecture & Setup

- Spawns the `mcp-debugger` CLI (`packages/mcp-debugger/dist/cli.mjs`) as a child process via `StdioClientTransport` (L36-43)
- Connects an MCP `Client` to the server over stdio (L45-52)
- Uses a shared `mcpClient` and `transport` across all tests in the suite (L22-24)
- `sessionId` (L24) is tracked per-test and cleaned up in `afterEach` (L78-90) and `afterAll` (L56-76)
- Test fixture script: `examples/javascript/simple_test.js` (L92)

### Lifecycle Hooks

- **`beforeAll`** (L26-54, timeout 30s): Validates CLI bundle exists, creates `StdioClientTransport` with `NODE_ENV=test`, instantiates and connects `Client`
- **`afterAll`** (L56-76): Best-effort session close, then closes `mcpClient` and `transport`
- **`afterEach`** (L78-90): Closes any open session, resets `sessionId` to `null`

### Test Cases

#### `should complete full JavaScript debugging cycle` (L94-256, timeout 60s)
Full 9-step workflow:
1. `create_debug_session` → verifies `sessionId` returned (L98-110)
2. `set_breakpoint` at line 14 → verifies `success: true` (L114-125)
3. `start_debugging` with `stopOnEntry: false, justMyCode: true` → verifies `state` contains `'paused'` (L129-146)
4. 1s stabilization wait (L149)
5. `get_stack_trace` → verifies non-empty `stackFrames` array (L153-165)
6. `get_local_variables` → verifies `variables` array exists (L169-181)
7. `step_over` → verifies `success: true`; optionally validates `location.{file,line}` and `context.{lineContent,surrounding}` (L185-207)
8. 1s wait (L210)
9. `evaluate_expression` with `'1 + 2'` → verifies result matches `/3/` (L214-227)
10. `continue_execution` → verifies `success: true` (L231-238)
11. 2s wait for script completion (L241)
12. `close_debug_session` → verifies `success: true`, sets `sessionId = null` (L245-252)

#### `should handle multiple breakpoints` (L258-295)
- Creates session, sets two breakpoints (lines 11 and 14), verifies both return `success: true`, then closes session.

#### `should retrieve source context` (L297-340)
- Creates session, calls `get_source_context` at line 14 with `linesContext: 3`, verifies `success: true` and that at least one of `lineContent`, `source`, or `context` is defined.

### Key Dependencies

- `@modelcontextprotocol/sdk/client/index.js` — MCP `Client` class
- `@modelcontextprotocol/sdk/client/stdio.js` — `StdioClientTransport` for spawning the server process
- `./smoke-test-utils.js` — `parseSdkToolResult` utility for unwrapping MCP tool call responses

### MCP Tool Names Used
`create_debug_session`, `set_breakpoint`, `start_debugging`, `get_stack_trace`, `get_local_variables`, `step_over`, `evaluate_expression`, `continue_execution`, `close_debug_session`, `get_source_context`

### Notable Patterns
- Non-null assertions (`mcpClient!`) used throughout since `beforeAll` guarantees initialization; tests will fail at connect if server is unavailable
- Optional checks on `stepResponse.location` and `stepResponse.context` (L195-207) make step_over location/context non-required assertions
- `parseSdkToolResult` wraps all tool call results uniformly
- `sessionId` guard in both `afterEach` and `afterAll` prevents double-close errors