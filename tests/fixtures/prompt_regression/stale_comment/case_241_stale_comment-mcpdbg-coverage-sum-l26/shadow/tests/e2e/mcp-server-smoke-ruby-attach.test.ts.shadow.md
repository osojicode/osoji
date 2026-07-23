# tests\e2e\mcp-server-smoke-ruby-attach.test.ts
@source-hash: 5f843fa11997e8b4
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:04Z

## Ruby Attach-Mode Smoke Tests via MCP Interface

End-to-end test file validating Ruby attach-mode debugging through the MCP server. Spawns a Ruby script under `rdbg --open --port <p>`, connects via the MCP `attach_to_process` tool, exercises breakpoints/locals/eval, then detaches without terminating the target process.

### Test Suite: `MCP Server Ruby Attach-Mode Smoke Test @requires-ruby` (L68–225)

Single Vitest `describe` block with:
- `beforeAll` (L75–103): Detects Ruby/rdbg availability; if present, spawns MCP server as a child process over stdio and connects an MCP `Client`. Times out at 30s.
- `afterAll` (L105–126): Closes debug session, disconnects MCP client, closes transport, and force-kills `rdbgProcess` with `SIGKILL` if still running.
- One `it` test (L128–224, timeout 120s): Full attach-debug-detach flow.

### Test Flow (single `it`, L128–224)
1. **Resolve executables** (L133–134): `findRubyExecutable()`, `findRdbgExecutable()` from `@debugmcp/adapter-ruby`.
2. **Get free port** (L136): `getFreePort()` binds to `127.0.0.1:0` and resolves the OS-assigned port.
3. **Spawn rdbg** (L139–147): `buildRdbgInvocation()` → `spawn()` with `--open --host 127.0.0.1 --port <port>`, stdio piped.
4. **Wait for rdbg ready** (L150–167): Polls stderr for `"wait for debugger connection"` string; rejects after 30s or premature exit.
5. **Create debug session** (L170–175): MCP tool `create_debug_session` with `language: 'ruby'`.
6. **Attach** (L177–183): MCP tool `attach_to_process` with `host`, `port`; asserts `success=true`, `state='paused'`.
7. **Set breakpoint at line 12** (L186–191): `set_breakpoint` on `examples/ruby/long_running.rb` line 12 (`puts` inside loop).
8. **Continue** (L193–194): `continue_execution` releases the load-suspension.
9. **Wait for pause** (L197–199): `waitForPausedState()` polls `get_stack_trace` up to 20×500ms; asserts `stackFrames[0].line === 12`.
10. **Inspect locals** (L201–206): `get_local_variables`; asserts `counter >= 1`, `message` contains `'tick'`.
11. **Evaluate expression** (L209–213): `evaluate_expression` with `'counter * 2'`; asserts `success=true`.
12. **Detach** (L216–220): `detach_from_process` with `terminateProcess: false`; asserts success.
13. **Process still alive** (L222–223): Waits 1s, asserts `rdbgProcess.exitCode === null`.

### Key Helper Functions

#### `getFreePort()` (L36–50)
Binds a TCP server to `127.0.0.1:0`, reads the assigned port from `srv.address()`, closes the server, resolves with the port number.

#### `waitForPausedState(client, sessionId, maxAttempts=20, intervalMs=500)` (L52–66)
Polls `get_stack_trace` MCP tool via `callToolSafely` up to `maxAttempts` times with `intervalMs` delay. Returns parsed result if `stackFrames` is non-empty, or `null` on timeout.

### MCP Server Configuration
- Launched via `process.execPath` (Node) pointing to `dist/index.js` with `--log-level info` (L86–88).
- Environment: inherits `process.env` plus `NODE_ENV=test` (L89–91).

### Dependencies
- **`@debugmcp/adapter-ruby`**: `findRubyExecutable`, `findRdbgExecutable`, `buildRdbgInvocation` for platform-aware Ruby/rdbg invocation.
- **`./smoke-test-utils.js`**: `parseSdkToolResult` (unwraps MCP SDK tool results), `callToolSafely` (wrapper around `client.callTool`).
- **`@modelcontextprotocol/sdk`**: `Client`, `StdioClientTransport` for MCP protocol.
- **`child_process.spawn`**: Launches the rdbg subprocess directly.
- **`net`**: Used only in `getFreePort()` for port discovery.

### Skip Behavior
If `findRubyExecutable()` or `findRdbgExecutable()` throws in `beforeAll`, `rubyAvailable` stays `false`. The single `it` block returns early at L129–131 without failing. MCP client setup is skipped entirely.

### Notable Constraints
- Target script path hardcoded to `examples/ruby/long_running.rb` relative to repo root (L135).
- Breakpoint line hardcoded to `12` — must match actual line in target script (L188–189).
- rdbg startup detection relies on stderr string `"wait for debugger connection"` (L158).
- Cleanup uses `SIGKILL` (not `SIGTERM`) for rdbg process (L122).