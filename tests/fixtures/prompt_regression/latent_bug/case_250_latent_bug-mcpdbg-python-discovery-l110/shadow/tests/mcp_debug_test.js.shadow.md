# tests\mcp_debug_test.js
@source-hash: 0d02e455df317a71
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:45Z

## Purpose
End-to-end integration test script that exercises the `debug-mcp-server` tools via HTTP POST requests to a locally running MCP server, simulating an LLM-driven debugging workflow against a Python Fibonacci example script.

## Configuration Constants (L12–L14)
- `MCP_SERVER_URL` (L12): Base URL for the MCP server, defaults to `http://localhost:3000`.
- `TEST_SCRIPT_PATH` (L13): Absolute path to `../examples/python/fibonacci.py`, resolved relative to `__dirname`.
- `SERVER_NAME` (L14): Fixed identifier `'debug-mcp-server'` sent in every tool request body.

## Core Functions

### `callTool(toolName, args)` (L17–L45)
Utility that sends a POST to `${MCP_SERVER_URL}/mcp-tool` with JSON body `{ server_name, tool_name, arguments }`. Logs tool name and args before calling, logs response after. Throws on non-2xx HTTP status or network error. Returns parsed JSON response.

### `sleep(ms)` (L48–L50)
Simple Promise-based delay helper used between debug steps.

### `runTest()` (L53–L171)
Main async orchestration function. Executes 9 sequential debug workflow steps:
1. **Create session** (L60–L70): Calls `create_debug_session` with `language: 'python'`, `name: 'Fibonacci Test'`. Extracts `sessionId` from result.
2. **Set breakpoint** (L74–L84): Calls `set_breakpoint` at `TEST_SCRIPT_PATH` line 38 (hardcoded as "buggy calculation").
3. **Start debugging** (L88–L100): Calls `start_debugging`, then waits 1000ms for breakpoint to be hit.
4. **Get variables** (L104–L109): Calls `get_variables`; does not check `success` flag.
5. **Evaluate expression** (L113–L119): Calls `evaluate_expression` with `expression: 'fibonacci_iterative(n)'`; does not check `success` flag.
6. **Step over** (L123–L131): Calls `step_over`, checks `success`.
7. **Get stack trace** (L135–L140): Calls `get_stack_trace`; does not check `success` flag.
8. **Continue execution** (L144–L152): Calls `continue_execution`, checks `success`.
9. **Close session** (L156–L164): Calls `close_debug_session`, checks `success`.

On any thrown error, logs and calls `process.exit(1)` (L169).

## Entry Point (L174–L177)
Calls `runTest()` at module level with a top-level `.catch` that also exits with code 1 on unhandled rejections.

## Dependencies
- `node-fetch` (L8): HTTP client for tool calls.
- `path` (L9): Resolves `TEST_SCRIPT_PATH`.

## Notable Patterns / Constraints
- The test is **not integrated into a test runner** (Jest, Mocha, etc.); it is a standalone script run directly with Node.
- Success checking is **inconsistent**: steps 1, 2, 3, 6, 8, 9 check `.success`; steps 4, 5, 7 do not.
- The 1-second `sleep` at L100 is a timing hack — if the debug server is slow the breakpoint may not be hit yet.
- All tool calls go through HTTP, so the MCP server must already be running at `localhost:3000` before this test executes.
- `sessionId` is read directly from `createSessionResult.sessionId` (L69) without null-guarding beyond the `.success` check.
