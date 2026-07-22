# tests\e2e\docker\docker-smoke-python.test.ts
@source-hash: ca8fb50374b1ff20
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:35Z

## Docker Python Smoke Tests

End-to-end test suite validating Python debugging functionality inside a Docker container via MCP (Model Context Protocol) client. All tests are skipped when `SKIP_DOCKER_TESTS=true`.

### Test Structure

**Suite:** `Docker: Python Debugging Smoke Tests` (L21–372), conditioned on `SKIP_DOCKER` (L19).

**Shared state (L22–25):**
- `mcpClient`: MCP SDK `Client` instance, initialized in `beforeAll`
- `cleanup`: async teardown function returned by `createDockerMcpClient`
- `sessionId`: tracks active debug session for per-test cleanup
- `containerName`: Docker container name, used for log retrieval on failure

### Lifecycle Hooks

**`beforeAll` (L27–43, timeout 240s):**
1. Builds Docker image `mcp-debugger:test` via `buildDockerImage`
2. Creates a uniquely-named container (`mcp-debugger-py-test-<timestamp>`)
3. Initializes `mcpClient` and `cleanup` via `createDockerMcpClient`

**`afterAll` (L45–69):**
- Closes any lingering debug session via `close_debug_session` MCP tool
- Runs `cleanup()` to tear down the Docker container
- Prints Docker container logs if `VITEST_FAILED` env var is set (diagnostic aid)

**`afterEach` (L71–83):**
- Closes active debug session and resets `sessionId = null` to prevent double-close

### Test Cases

#### `should complete full Python debugging cycle in Docker` (L85–287, timeout 120s)
Full 10-step debugging workflow against `examples/python/simple_test.py`:
1. **Create session** — language `python`, name `docker-python-smoke`
2. **Set breakpoint** — line 11 (swap operation)
3. **Start debugging** — `stopOnEntry: false`, `justMyCode: true`; asserts state contains `'paused'`
4. **Get stack trace** — validates non-empty `stackFrames` array
5. **Get variables before swap** — asserts `a='1'`, `b='2'`
6. **Step over** — advances past swap line
7. **Get variables after swap** — asserts `a='2'`, `b='1'`
8. **Evaluate expression** — `a + b`, expects result matching `/3/`
9. **Continue execution**
10. **Close session**

On `start_debugging` failure, fetches and prints Docker container logs before re-throwing (L148–160).

#### `should handle multiple breakpoints in Docker` (L289–327, timeout 60s)
Sets two breakpoints (lines 10 and 11) and verifies both return `success: true`. No actual execution.

#### `should retrieve source context in Docker` (L329–371, timeout 60s)
Creates a session, calls `get_source_context` for line 10 with 3 lines of context. Verifies `success: true` and presence of at least one of `lineContent`, `source`, or `context` in the response.

### Path Translation
`hostToContainerPath` (L88, L291, L331) converts host filesystem paths to container-internal paths for use in MCP tool arguments.

### Key Constants
- `ROOT` (L17): Three levels up from `__dirname`, resolves to repo root
- `SKIP_DOCKER` (L19): Read from `process.env.SKIP_DOCKER_TESTS`
- Script under test: `examples/python/simple_test.py`

### MCP Tool Names Used
- `create_debug_session`
- `set_breakpoint`
- `start_debugging`
- `get_stack_trace`
- `get_local_variables`
- `step_over`
- `evaluate_expression`
- `continue_execution`
- `close_debug_session`
- `get_source_context`

### Dependencies
- `./docker-test-utils.js`: `buildDockerImage`, `createDockerMcpClient`, `hostToContainerPath`, `getDockerLogs`
- `../smoke-test-utils.js`: `parseSdkToolResult` — unwraps raw MCP SDK tool results into plain objects
- `@modelcontextprotocol/sdk/client/index.js`: `Client` type