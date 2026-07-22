# tests\e2e\docker\docker-smoke-javascript.test.ts
@source-hash: 99ce30630b912b15
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:14Z

## Docker JavaScript Smoke Tests

End-to-end smoke test suite validating JavaScript debugging functionality via MCP (Model Context Protocol) tool calls against a real Docker container running the `mcp-debugger:test` image.

### Architecture
- Uses `vitest` as test runner; entire suite is skipped when `SKIP_DOCKER_TESTS=true` (L22–24)
- Suite-level lifecycle: `beforeAll` builds Docker image and creates MCP client (L30–46), `afterAll` tears down session/container (L48–72), `afterEach` closes the debug session between tests (L74–86)
- All MCP tool interactions go through `mcpClient.callTool(...)`, results parsed by `parseSdkToolResult`
- Path mapping: host filesystem paths are converted to container paths via `hostToContainerPath` before being passed as tool arguments

### Key Constants
- `ROOT` (L20): Project root resolved as 3 levels above `__dirname` (`../../..`)
- `SKIP_DOCKER` (L22): Controls conditional skip via `SKIP_DOCKER_TESTS` env var
- Image name: `mcp-debugger:test` (L32, L37)
- Container name pattern: `mcp-debugger-js-test-${Date.now()}` (L35)

### Shared State (suite-scoped)
- `mcpClient` (L25): MCP SDK `Client` instance; initialized in `beforeAll`
- `cleanup` (L26): Async cleanup function returned by `createDockerMcpClient`
- `sessionId` (L27): Tracked session ID; reset to `null` after each test
- `containerName` (L28): Used for log retrieval on failure

### Test Cases

#### `should complete full JavaScript debugging cycle in Docker` (L88–290, timeout 120s)
Full 9-step cycle on `examples/javascript/mcp_target.js`:
1. `create_debug_session` → asserts `sessionId` defined (L98–110)
2. `set_breakpoint` at line 44 → asserts `success: true` (L114–125)
3. `start_debugging` with `stopOnEntry: false, justMyCode: true` → asserts state contains `'paused'` (L130–197); on error, dumps Docker container logs via `getDockerLogs` and `execAsync` (`docker logs --tail 200`), also tries `docker exec cat /tmp/docker-test.log`
4. `get_stack_trace` → asserts `stackFrames` is non-empty array (L204–216)
5. `get_local_variables` → asserts `variables` is array (L220–231)
6. `step_over` → asserts `success: true` (L235–242)
7. `evaluate_expression` with `'1 + 2'` → asserts result matches `/3/` (L249–261)
8. `continue_execution` → asserts `success: true` (L265–272)
9. `close_debug_session` → asserts `success: true` (L279–287)

#### `should step into nested JavaScript frames in Docker` (L292–387, timeout 120s)
Uses `mcp_target.js`, breakpoint at line 48. Validates `step_into` navigates into `deepFunction` (asserts `topAfter.name.toLowerCase()` contains `'deepfunction'` and line < 48) (L365–371).

#### `should step over top-level const declarations in Docker` (L389–469, timeout 120s)
Uses `examples/javascript/test-simple.js`, breakpoint at line 3. Validates `step_over` advances to line 4 (L453).

#### `should handle multiple breakpoints in Docker` (L471–509, timeout 60s)
Uses `mcp_target.js`, sets two breakpoints at lines 44 and 53, asserts both `success: true`. Does not start debugging.

#### `should retrieve source context in Docker` (L511–553, timeout 60s)
Uses `mcp_target.js`. Calls `get_source_context` at line 44 with `linesContext: 3`, asserts `success: true` and that one of `lineContent`, `source`, or `context` is defined on response.

### MCP Tool Names Used
`create_debug_session`, `set_breakpoint`, `start_debugging`, `get_stack_trace`, `get_local_variables`, `step_over`, `step_into`, `evaluate_expression`, `continue_execution`, `close_debug_session`, `get_source_context`

### Notable Patterns
- `afterAll` checks `process.env.VITEST_FAILED` (L65) to conditionally print container logs — note this env var is not a standard Vitest variable and may not be set reliably
- Defensive error handling in `start_debugging` step fetches logs from two sources before re-throwing
- 1–2 second `setTimeout` stabilization delays after `start_debugging`, `step_over`, `step_into` (L200, L245, L333, L356, L430, L440)