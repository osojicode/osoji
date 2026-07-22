# tests\adapters\python\integration\python_debug_workflow.test.ts
@source-hash: b9aacd23e9e870c3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:09Z

## Python Debug Workflow Integration Test

Integration test suite that validates a full Python debugging workflow via an MCP (Model Context Protocol) server. Spawns a real MCP server process via stdio transport, connects an SDK client, and exercises the complete debugpy-backed debug session lifecycle.

### Architecture
- Spawns the compiled server (`dist/index.js`) as a child process via `StdioClientTransport` (L51-55)
- Uses `@modelcontextprotocol/sdk` `Client` to invoke MCP tools over stdio
- Module-level `client` variable (L12) shared across `beforeAll`/`afterAll` and test cases
- Server log file written to `tests/adapters/integration_test_server.log` (L35), cleaned on each run

### Key Functions

**`startTestServer()` (L15-68)**: Async setup function called in `beforeAll`. Resolves server script at `../../../../dist/index.js` relative to this file. Filters `process.env` to remove `undefined` values (L29-34). Calls `ensurePythonOnPath` to inject Python into the spawned env (L44). Creates `StdioClientTransport` with `--log-level debug --log-file <path>` args (L53). Connects `Client`, which spawns the server and performs MCP `initialize` handshake.

**`stopTestServer()` (L70-81)**: Calls `client.close()` to terminate server process. Nullifies `client` on completion or failure.

**`delay(ms)` (L84)**: Simple promise-based sleep utility.

**`parseToolResult(rawResult)` (L86-93)**: Extracts and JSON-parses the `content[0].text` field from MCP tool call responses. Throws on malformed responses.

**`waitForStackFrames(client, sessionId, timeoutMs, pollInterval)` (L95-121)**: Polls `get_stack_trace` tool until `stackFrames.length > 0` or timeout (default 15s, 500ms interval). Returns parsed stack trace result or throws timeout error.

**`persistFailurePayload(testName, payload)` (L281-290)**: Writes failure JSON to `logs/tests/adapters/failures/<testName>-<timestamp>.json`. Called only on CI dry-run failure (L259).

### Test Suite: `Python Debugging Workflow - Integration Test @requires-python` (L123-280)
Suite timeout: 60 seconds. Fixture: `tests/fixtures/python/debug_test_simple.py`, breakpoint line 13 (`c = a + b`).

**Test 1: `should complete a full debug session and inspect local variables` (L136-228)**
Full 9-step workflow:
1. `list_debug_sessions` — verifies array response
2. `create_debug_session` (language: `python`) — captures `sessionId`
3. `set_breakpoint` at line 13 — verifies absolute path and line echo
4. `start_debugging` with `stopOnEntry: true` — expects `state === 'paused'`
5. `continue_execution` — resumes to breakpoint
6. `get_stack_trace` via `waitForStackFrames` — verifies frame in `sample_function` at line 13
7. `get_scopes` with `frameId` — finds `Locals` scope, extracts `variablesReference`
8. `get_variables` with locals ref — asserts `a === '5'` (int), `b === '10'` (int)
9. `close_debug_session`

**Test 2: `should perform a dry run for start_debugging and log the command` (L230-279)**
Creates a separate session, calls `start_debugging` with `dryRunSpawn: true`. Expects:
- `success === true`
- `state === 'stopped'`
- `data.dryRun === true`
- `data.message` contains `"Dry run spawn command logged by proxy."`
On CI failure, persists payload via `persistFailurePayload`. Closes dry-run session on completion.

### MCP Tool Names Used
`list_debug_sessions`, `create_debug_session`, `set_breakpoint`, `start_debugging`, `continue_execution`, `get_stack_trace`, `get_scopes`, `get_variables`, `close_debug_session`

### Dependencies
- `@modelcontextprotocol/sdk` — MCP client and stdio transport
- `@debugmcp/shared` — `StackFrame`, `Variable` types for assertion typing
- `@vscode/debugprotocol` — `DebugProtocol.Scope` type for scope assertion
- `./env-utils.js` — `ensurePythonOnPath` mutates env record to inject Python
- `vitest` — test framework

### Notable Patterns
- `process.execPath` used as the Node.js command to run the server (L52), ensuring same Node version
- CI-specific stderr diagnostics for PATH after `ensurePythonOnPath` on Windows (L45-49)
- `persistFailurePayload` only called for dry-run test on CI (L255-260), not for the main workflow test
- `beforeAll` timeout is 30s (L130), individual test inherits suite 60s timeout