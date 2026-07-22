# examples\debugging\test-sse-js-debug-fix.js
@source-hash: 7b20fcaf081d0a94
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:13Z

## Purpose
End-to-end integration test script that verifies the fix for a timing bug in SSE-based JavaScript debugging, where `stackTrace` was called before the child debug session became active. Spawns a local SSE MCP server, connects an MCP client, creates a JS debug session, sets a breakpoint, starts debugging, then immediately requests a stack trace to confirm the race condition is resolved.

## Key Symbols

### `waitForPort(port, maxAttempts)` (L15–34)
Poll helper that repeatedly attempts a TCP connection to `localhost:port`. Returns `true` on success; throws after `maxAttempts` (default 30) × 1s attempts. Uses Node's `net` module (required inline at L16).

### `runTest()` (L36–205)
Core async test driver. Sequence:
1. **Spawn SSE server** (L45–53): runs `dist/index.js sse -p 3100 --log-level debug` via `child_process.spawn`, piping stdout/stderr.
2. **Wait for readiness** (L66): calls `waitForPort(PORT)`.
3. **Connect MCP client** (L71–78): creates `Client` + `SSEClientTransport` pointed at `http://localhost:3100/sse`.
4. **Create debug session** (L82–96): calls `create_debug_session` tool with `language: 'javascript'`; parses `sessionId` from `content[0].text`.
5. **Set breakpoint** (L103–110): calls `set_breakpoint` at line 11 of `examples/javascript/simple_test.js`.
6. **Start debugging** (L115–122): calls `start_debugging`.
7. **Get stack trace** (L129–134): the critical timing test — calls `get_stack_trace` immediately after start.
8. **Assert stack frames** (L142–167): exits with code 1 if `stackData.stackFrames` is empty/missing.
9. **Get local variables** (L148–161): optional follow-up call to `get_local_variables`.
10. **Cleanup** (L171–177): calls `close_debug_session`.
- `finally` block (L182–203): closes MCP client, sends `SIGTERM` to server with 3s graceful timeout, falls back to `SIGKILL`.

### Module-level runner (L208–211)
Calls `runTest()` and exits with code 1 on any unhandled rejection.

## Constants
- `PORT = 3100` (L13): hardcoded test port, chosen to avoid conflicts.

## Dependencies
- `child_process.spawn` — server lifecycle management
- `@modelcontextprotocol/sdk/client/index.js` → `Client`
- `@modelcontextprotocol/sdk/client/sse.js` → `SSEClientTransport`
- `path`, `net` (inline) — path resolution and TCP polling

## MCP Tool Calls Made
| Tool | Purpose |
|------|---------|
| `create_debug_session` | Create JS debug session, returns `sessionId` |
| `set_breakpoint` | Set BP at `simple_test.js:11` |
| `start_debugging` | Launch debugger |
| `get_stack_trace` | Core regression assertion |
| `get_local_variables` | Secondary assertion |
| `close_debug_session` | Cleanup |

## Critical Design Notes
- The test targets a **specific race condition**: `get_stack_trace` is called with no artificial delay after `start_debugging` — this is intentional (L125–127).
- Server binary path is relative to `__dirname/dist/index.js` (L46) — requires a prior build step.
- `sessionId` extraction uses optional chaining + JSON parse on `content[0].text` (L90–92); a parse failure silently yields `null`, caught by the guard at L94.
- Server shutdown uses `Promise.race` with a 3s timeout (L196–200) before escalating to `SIGKILL`.