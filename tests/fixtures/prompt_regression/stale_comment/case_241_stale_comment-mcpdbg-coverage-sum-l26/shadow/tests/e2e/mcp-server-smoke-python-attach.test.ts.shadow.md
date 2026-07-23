# tests\e2e\mcp-server-smoke-python-attach.test.ts
@source-hash: cb599e622f717f69
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:33Z

## Python Attach-Mode Smoke Test via MCP Interface

End-to-end test validating Python debugpy attach-mode debugging through the MCP server interface. Specifically serves as a regression test for issue #145 (attach handshake deadlock where debugpy emits `initialized` only after receiving the attach request, and only responds to attach after `configurationDone`).

### Test Structure

Single `describe` block (L88) with one primary test case (L156) under the tag `@requires-python`. Uses `beforeAll`/`afterAll`/`afterEach` hooks for MCP client lifecycle and subprocess cleanup.

### Key Helpers

**`getFreePort()` (L48–62):** Async utility that finds a free TCP port by creating a temporary `net.Server` bound to port 0 on `127.0.0.1`, reading the assigned port, then closing the server. Returns a `Promise<number>`.

**`waitForPausedState()` (L68–86):** Polls `get_stack_trace` MCP tool up to `maxAttempts` times (default 20) at `intervalMs` intervals (default 500ms). Returns the stack response object when non-empty frames are found and the optional `validate` predicate passes, or `null` on timeout.

### Test Lifecycle

**`beforeAll` (L94–115):** Spawns MCP server via `StdioClientTransport` running `dist/index.js --log-level info` using the current Node.js executable. Creates and connects an MCP `Client` named `python-attach-smoke-test-client`. 30s timeout.

**`afterAll` (L117–138):** Closes debug session if still open, closes MCP client and transport, sends `SIGKILL` to the Python subprocess if still running.

**`afterEach` (L140–154):** Closes debug session and kills Python subprocess after each test — ensures clean state between reruns.

### Main Test Case: L156–348 (60s timeout)

1. **Skip guard (L158–163):** Runs `python3 -c "import debugpy"` via `execSync`; returns early (soft skip) if Python/debugpy not available.
2. **Spawn debugpy target (L169–213):** Calls `getFreePort()`, then spawns `python3 -m debugpy --listen 127.0.0.1:<port> examples/python/attach_loop.py`. Waits up to 15s for the string `ATTACH_LOOP_READY` on stdout or stderr — proves debugpy listener is ready before proceeding.
3. **Create debug session (L218–230):** MCP tool `create_debug_session` with `language: 'python'`. Hard-asserts `sessionId` is defined.
4. **Set breakpoint (L232–245):** MCP tool `set_breakpoint` at `scriptPath:7` (line 7 = `result = a + b` inside `compute()`). Hard-asserts `success: true`.
5. **Attach (L247–263):** MCP tool `attach_to_process` with `host: '127.0.0.1'` and the dynamic `port`. Hard-asserts `success: true` and `state: 'paused'` — the paused state proves the attach-first deadlock is resolved.
6. **Continue (L265–273):** MCP tool `continue_execution` to resume from the post-attach pause. Hard-asserts `success: true`.
7. **Wait for breakpoint hit (L276–294):** Calls `waitForPausedState` with a validate predicate checking `frames[0].name.toLowerCase().includes('compute')`. Hard-asserts non-null result, non-empty frames, top frame name contains `compute`, and top frame line equals 7.
8. **Verify local variables (L296–319):** MCP tool `get_local_variables`. Hard-asserts `success: true`, `variables` is a non-empty array, `a === '42'`, `b === '58'`.
9. **Continue after breakpoint (L321–329):** MCP tool `continue_execution`. Hard-asserts `success: true`.
10. **Detach without killing target (L331–339):** MCP tool `close_debug_session`. Waits 1s then hard-asserts `pyProcess.exitCode === null` — proves `terminateDebuggee: false` attach-mode detach.
11. **Cleanup (L341–347):** `finally` block sends `SIGKILL` to Python subprocess.

### Platform Handling (L43)
`PYTHON_CMD` is `'python'` on Windows, `'python3'` on Linux/macOS.

### Script Under Test
`examples/python/attach_loop.py` — expected to print `ATTACH_LOOP_READY`, then loop calling `compute(a=42, b=58)` approximately every 500ms with a breakpoint target at line 7.

### Dependencies
- `@modelcontextprotocol/sdk`: `Client`, `StdioClientTransport`
- `./smoke-test-utils`: `parseSdkToolResult`, `callToolSafely`
- Node built-ins: `net`, `path`, `child_process`
- MCP server binary: `dist/index.js` (must be built before running)
