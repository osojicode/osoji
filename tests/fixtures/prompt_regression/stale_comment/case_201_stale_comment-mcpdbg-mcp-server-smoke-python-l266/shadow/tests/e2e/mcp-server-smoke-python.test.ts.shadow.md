# tests\e2e\mcp-server-smoke-python.test.ts
@source-hash: 583f300f6da782be
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:00Z

## Python MCP Server Smoke Tests

End-to-end smoke tests validating Python debugging functionality exposed via the MCP (Model Context Protocol) interface. Tests run against a live MCP server process launched as a subprocess and communicate via stdio transport.

### Architecture
- Spawns a real MCP server (`dist/index.js`) via `StdioClientTransport` (L33-40)
- Uses `@modelcontextprotocol/sdk` `Client` to invoke MCP tools over stdio
- Test fixture shared across tests: `mcpClient`, `transport`, `sessionId` (L25-27)
- `beforeAll` (L29-52): Connects MCP client with 30s timeout
- `afterAll` (L54-73): Closes session (if any), then client and transport
- `afterEach` (L75-85): Cleans up `sessionId` after each test to prevent leakage

### Test Cases

**`should complete Python debugging flow cleanly` (L87-243, 60s timeout)**
Full debug lifecycle: create session → set breakpoint at line 32 → start debugging → wait 3s → get stack trace (expects <10 frames, top frame near line 32) → get scopes/variables → step over → get stack trace after step → continue execution → close session. Validates `location` and `context` fields on step result.

**`should handle multiple breakpoints in Python` (L245-289)**
Creates session, sets two breakpoints (lines 32, 46), verifies both are accepted (verified: false), then closes. Pure breakpoint registration test — does not actually run the script.

**`should evaluate expressions in Python context` (L291-349)**
Creates session, starts with `stopOnEntry: true`, waits 3s, evaluates `'1 + 2'` (expects result containing `'3'`), tests statement rejection via `'x = 99'` (expects error or `success: false`), closes session.

**`should get source context for Python files` (L351-385)**
Creates session, calls `get_source_context` for line 32 with 5-line context, asserts source contains `'factorial'` and `currentLine === 32`, closes.

**`should handle step into for Python` (L387-453)**
Creates session, sets breakpoint at line 32, starts debugging, waits 3s, calls `step_into`, checks stack depth > 1 after stepping into factorial function, closes. Accepts graceful failure (`success === false`).

### Key Patterns
- All MCP tool calls use `mcpClient!.callTool(...)` directly for session create/start, and `callToolSafely(mcpClient!, ...)` for all other operations (swallows errors)
- `parseSdkToolResult` used to extract typed response from raw MCP tool results
- Python-specific known characteristics documented in file header (L1-11): unverified breakpoints, clean stack traces, stable variable refs, absolute paths required, expression-only eval
- Target script: `examples/python/test_python_debug.py`, breakpoint lines 32 and 46
- Fixed `setTimeout` waits used as synchronization: 3000ms for breakpoint/stop events, 2000ms post-step

### Dependencies
- `vitest` test framework (describe/it/expect/beforeAll/afterAll/afterEach)
- `@modelcontextprotocol/sdk` Client + StdioClientTransport
- `./smoke-test-utils.js`: `parseSdkToolResult`, `callToolSafely`
- MCP server binary: `../../dist/index.js`
- Python test fixture: `../../examples/python/test_python_debug.py`
