# tests\adapters\python\integration\python_debug_workflow.test.ts
@source-hash: b9aacd23e9e870c3
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:30Z

## Python Debug Workflow Integration Test

End-to-end integration test for a Python debugging MCP (Model Context Protocol) server. Spawns a real MCP server subprocess via stdio transport, drives a complete DAP-based debug session against a Python fixture script, and verifies variable inspection at a breakpoint.

### Architecture
- Uses `@modelcontextprotocol/sdk` Client + StdioClientTransport to spawn `dist/index.js` as a child process (L51-55)
- Communicates with the server exclusively via MCP tool calls (`client.callTool`)
- All tool responses are parsed from JSON embedded in `content[0].text` by `parseToolResult` (L86-93)

### Key Symbols

**`startTestServer` (L15-68):** Resolves server script at `../../../../dist/index.js`, filters `process.env` to a clean string map, calls `ensurePythonOnPath` to patch PATH, creates `StdioClientTransport` with debug log flags, and connects the MCP client. Sets module-level `client`.

**`stopTestServer` (L70-81):** Closes MCP client connection (which terminates server process). Nulls `client`.

**`delay` (L84):** Simple promise-based sleep utility.

**`parseToolResult` (L86-93):** Extracts and JSON-parses the `content[0].text` field from a raw MCP tool result. Throws on malformed responses.

**`waitForStackFrames` (L95-121):** Polling loop (default 15s timeout, 500ms interval) that calls `get_stack_trace` tool until stack frames are non-empty. Final call after timeout raises a descriptive error.

**`persistFailurePayload` (L281-290):** On CI failures, writes JSON failure payload to `logs/tests/adapters/failures/<testName>-<timestamp>.json`.

### Test Suite: `Python Debugging Workflow - Integration Test @requires-python` (L123-280)
- **Fixture:** `tests/fixtures/python/debug_test_simple.py`, breakpoint at line 13 (`c = a + b` in `sample_function`)
- **Suite timeout:** 60 000 ms; `beforeAll` timeout: 30 000 ms

#### Test 1: `should complete a full debug session and inspect local variables` (L136-228)
Full 9-step workflow:
1. `list_debug_sessions` — verifies sessions array
2. `create_debug_session` (language=python) — captures `sessionId`
3. `set_breakpoint` at line 13 — verifies absolute path roundtrip
4. `start_debugging` with `stopOnEntry: true` — expects `state === 'paused'`
5. `continue_execution` — resumes past entry stop
6. `waitForStackFrames` — polls until stopped at breakpoint; verifies frame name=`sample_function`, line=13
7. `get_scopes` — finds `Locals` scope, captures `variablesReference`
8. `get_variables` — verifies `a=5 (int)`, `b=10 (int)`
9. `close_debug_session`

#### Test 2: `should perform a dry run for start_debugging and log the command` (L230-279)
- Creates a fresh session, calls `start_debugging` with `dryRunSpawn: true`
- Expects `success=true`, `state='stopped'`, `data.dryRun=true`, `data.message` contains `"Dry run spawn command logged by proxy."`
- On CI failure, calls `persistFailurePayload` before asserting
- Cleans up session; 1s delay for log flushing

### MCP Tool Names Used
- `list_debug_sessions`, `create_debug_session`, `set_breakpoint`, `start_debugging`, `continue_execution`, `get_stack_trace`, `get_scopes`, `get_variables`, `close_debug_session`

### Dependencies
- `@modelcontextprotocol/sdk/client` — MCP client + stdio transport
- `@debugmcp/shared` — `StackFrame`, `Variable` types
- `@vscode/debugprotocol` — `DebugProtocol.Scope` type for scope inspection
- `./env-utils.js` — `ensurePythonOnPath` patches PATH for Python availability
- `dist/index.js` (runtime) — the MCP debug server under test

### Invariants & Constraints
- `client` is module-level; shared across all tests in the suite (single server lifecycle per suite)
- Server is spawned with `--log-level debug --log-file <path>` flags; log file is deleted and recreated on each run
- PATH is sanitized on Windows CI via `ensurePythonOnPath` before transport creation
- All test assertions depend on `dist/index.js` being pre-built