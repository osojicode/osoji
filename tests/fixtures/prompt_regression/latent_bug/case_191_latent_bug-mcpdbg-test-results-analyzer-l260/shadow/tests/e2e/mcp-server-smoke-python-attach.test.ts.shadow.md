# tests\e2e\mcp-server-smoke-python-attach.test.ts
@source-hash: cb599e622f717f69
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:05Z

## Python Attach-Mode Smoke Tests via MCP Interface

End-to-end test suite validating Python debugpy attach-mode debugging through the MCP server interface. Specifically tests the regression fix for issue #145 (attach handshake deadlock), where debugpy emits `initialized` only after receiving the attach request and only responds after `configurationDone`.

### Architecture

- Spawns a real MCP server subprocess via `StdioClientTransport` (L97-104)
- Spawns a Python `debugpy` target process listening on a dynamically allocated TCP port (L174-181)
- Communicates entirely through the `@modelcontextprotocol/sdk` `Client` API
- Test fixture script: `examples/python/attach_loop.py` — expected to print `ATTACH_LOOP_READY` on stdout/stderr when ready (L192)

### Key Symbols

**`getFreePort()` (L48-62):** Allocates a free TCP port by briefly binding to port 0 on `127.0.0.1`, then resolving with the assigned port number before closing the server.

**`waitForPausedState()` (L68-86):** Polls `get_stack_trace` MCP tool up to `maxAttempts` times (default 20) with `intervalMs` delay (default 500ms). Optionally filters frames with a `validate` callback. Returns the result object with `stackFrames` or `null` on timeout.

**`describe` block (L88-349):** Single `describe` suite with shared state:
- `mcpClient: Client | null` — MCP SDK client
- `transport: StdioClientTransport | null` — stdio transport to MCP server subprocess
- `sessionId: string | null` — active debug session ID
- `pyProcess: ChildProcess | null` — the running debugpy target process

**`beforeAll` (L94-115):** Starts MCP server at `dist/index.js` with `--log-level info`, connects client. 30s timeout.

**`afterAll` (L117-138):** Closes debug session if open, closes MCP client and transport, kills `pyProcess` with `SIGKILL`.

**`afterEach` (L140-154):** Cleans up `sessionId` and `pyProcess` between tests.

### Primary Test: `should attach to a running debugpy target...` (L156-348)

Execution sequence:
1. **Prerequisite check** (L158-163): `execSync` checks `import debugpy`; skips gracefully if unavailable.
2. **Port allocation** (L169): `getFreePort()` for the debugpy listener.
3. **Target spawn** (L174-181): `spawn(PYTHON_CMD, ['-m', 'debugpy', '--listen', '127.0.0.1:{port}', scriptPath])` — waits for `ATTACH_LOOP_READY` marker (L183-213), 15s timeout.
4. **Create session** (L219-229): `create_debug_session` with `language='python'`.
5. **Set breakpoint** (L233-245): `set_breakpoint` on line 7 of `attach_loop.py` (inside `compute()`).
6. **Attach** (L250-263): `attach_to_process` with `host='127.0.0.1'`, `port=debugPort`. Asserts `success=true` and `state='paused'` — this is the regression assertion for the handshake deadlock.
7. **Continue** (L267-273): `continue_execution` to resume from post-attach pause.
8. **Poll breakpoint** (L277-279): `waitForPausedState` with validator requiring top frame name contains `'compute'`.
9. **Stack assertions** (L282-294): Non-empty frames, top frame is `compute()` at line 7.
10. **Variables** (L298-319): `get_local_variables`, asserts `a='42'` and `b='58'`.
11. **Continue again** (L323-329): Resume after breakpoint.
12. **Detach** (L334-339): `close_debug_session`, waits 1s, asserts `pyProcess.exitCode === null` (target survived detach).

### Platform Handling

- `PYTHON_CMD` (L43): `'python'` on Windows, `'python3'` on Linux/macOS.
- Resolves `__dirname` via `fileURLToPath(import.meta.url)` (L38-40) for ESM compatibility.
- ROOT is two levels up from test file: `path.resolve(__dirname, '../..')` (L40).

### Test Timeout

The single test has a 60-second timeout (L348). `beforeAll` has 30s.

### Dependencies

- `smoke-test-utils.js`: `parseSdkToolResult` (parses MCP tool call responses), `callToolSafely` (error-safe tool call wrapper)
- `@modelcontextprotocol/sdk`: `Client`, `StdioClientTransport`
- Fixture: `examples/python/attach_loop.py` — must define a `compute(a, b)` function with `result = a + b` at line 7, loop calling it with `a=42, b=58` every ~500ms, print `ATTACH_LOOP_READY` at startup