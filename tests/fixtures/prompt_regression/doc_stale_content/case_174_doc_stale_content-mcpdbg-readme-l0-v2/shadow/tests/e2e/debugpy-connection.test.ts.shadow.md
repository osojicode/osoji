# tests\e2e\debugpy-connection.test.ts
@source-hash: 87b72c82e14d5819
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:49Z

## E2E Test: MCP Server ↔ debugpy Connection

End-to-end test suite verifying the full integration path from MCP SDK client → MCP server (SSE mode) → debugpy (DAP) server. Tests real Python process spawning, real DAP communication, and real breakpoint/stepping behavior. No mocking.

### Architecture & Flow

1. **beforeAll** (L196–232): Spawns a real debugpy server (`tests/fixtures/python/debugpy_server.py`) on default port 5679, finds a random available port (49152–65535), spawns MCP server (`dist/index.js`) in SSE mode, polls `/health` until ready, then connects an MCP SDK client via SSE transport.
2. **afterAll** (L234–237): Calls centralized `cleanup()`.
3. Tests call MCP tools via `mcpSdkClient.callTool(...)` and parse results with `parseSdkToolResult`.

### Key Symbols

- **`cleanup()`** (L29–98): Centralized teardown. Lists/closes all active debug sessions via MCP tool, closes SDK client, kills MCP and debugpy processes, waits 500ms for socket release.
- **`parseSdkToolResult(rawResult)`** (L101–108): Extracts and JSON-parses `content[0].text` from an MCP `ServerResult`. Throws on invalid structure.
- **`findAvailablePort()`** (L113–148): Probes random ephemeral ports (up to 10 attempts) by binding a TCP server, resolves with a free port. Adds 200ms delay after close for Windows port release.
- **`startDebugpyServer(port?)`** (L150–184): Spawns `python`/`python3 debugpy_server.py --port <port>`, resolves when stdout emits `"Debugpy server is listening!"`. 5-second startup timeout.
- **`startMcpServer(port)`** (L186–193): Spawns `node dist/index.js sse -p <port> --log-level debug`. Readiness is polled externally via `/health`.

### Test Cases

**`'should create a debug session successfully'`** (L239–262):
- Calls `create_debug_session` (python, 'E2E Test Session')
- Asserts `sessionId` returned
- Verifies session appears in `list_debug_sessions`
- Closes session, asserts `success: true`

**`'should successfully debug a Python script'`** (L264–400):
- Creates session, writes temp Python script to `temp_e2e_test_at_root.py` (fibonacci + sleep)
- Calls `start_debugging` with `stopOnEntry: true`
- Waits 2s fixed delay for debugger readiness
- Sets breakpoint at line 4 (print after `time.sleep`)
- Calls `continue_execution`
- Polls `get_stack_trace` until `stackFrames[0].line === 4` (10s timeout, 200ms interval)
- Asserts top frame is at line 4 in the temp script, name `<module>`
- Calls `step_over`, then `continue_execution`
- Cleans up temp file and closes session in `finally`

### MCP Tools Exercised
`create_debug_session`, `list_debug_sessions`, `close_debug_session`, `start_debugging`, `set_breakpoint`, `continue_execution`, `get_stack_trace`, `step_over`

### Key Constraints
- Requires `dist/index.js` to exist (build must run first)
- Requires `python`/`python3` in PATH with `debugpy` installed
- All tests share a single module-level MCP client and process state (L22–26)
- `TEST_TIMEOUT = 60000` ms applies to beforeAll and each test
- The fixed 2s `delay(2000)` at L318 is an acknowledged limitation (comment at L315–317)