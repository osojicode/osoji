# tests\e2e\mcp-server-smoke-javascript-sse.test.ts
@source-hash: 10a187fcc8d58ac4
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:15Z

## E2E Smoke Test: JavaScript SSE Transport Debugging

End-to-end test validating that JavaScript debugging works correctly through the SSE (Server-Sent Events) MCP transport. This test specifically reproduces and verifies the fix for a critical IPC channel corruption bug where console output during SSE server startup would corrupt parent-child process IPC channels, causing JavaScript debugging to fail with empty stack traces.

### Critical Context (L1-25)
The file-level comment documents a week-long diagnosis: when `stdio: 'inherit'` is used (matching `start-sse-server.cmd` production environment), any `console.log` during proxy process initialization corrupts the IPC channel. The fix requires `hasSSE ||` in `shouldSilenceConsole` logic in `src/index.ts`. This test intentionally uses `stdio: 'inherit'` (L177) to validate the fix holds.

### Module-Level State (L39-42)
- `mcpSdkClient: Client | null` — MCP SDK client instance, cleaned up in `afterEach`
- `sseServerProcess: ChildProcess | null` — spawned SSE server process, killed in `afterEach`
- `serverPort: number | null` — dynamically allocated port for each test run
- `projectRoot: string` — `process.cwd()` captured at module load

### Test Suite: `'MCP Server E2E JavaScript SSE Test'` (L44-542)

#### `afterEach` cleanup (L46-101)
Handles graceful shutdown with SIGTERM → 2-second wait → SIGKILL fallback, then resets all module-level state. Always runs even on test failure.

#### `findAvailablePort()` (L106-143)
Picks a random port in the ephemeral range (49152-65535), probes it with a temporary TCP server, retries up to 10 times on `EADDRINUSE`/`EACCES`. Adds 200ms delay after port release for Windows compatibility.

#### `startSSEServer(options, maxRetries=3)` (L153-246)
Spawns `dist/index.js sse -p <port> --log-level debug` via `process.execPath`. **Critical**: uses `stdio: 'inherit'`. Readiness is determined via `waitForHealthEndpoint()` polling. Supports up to 3 retry attempts with fresh port allocation on failure. 30-second startup timeout per attempt (uses `TEST_TIMEOUT` constant). Cleans up failed process before retry.

#### `ExecuteSequenceOptions` interface (L251-257)
- `launchArgs`: optional DAP launch arguments (`stopOnEntry`, `justMyCode`) or `null` to omit entirely
- `stackTraceBeforeLocals`: controls ordering of stack trace vs local variable retrieval

#### `executeJavaScriptDebugSequence(client, scriptPath, sessionName, options)` (L259-428)
Core debug workflow orchestrator. Steps:
1. `create_debug_session` with `language: 'javascript'` (L273-284)
2. `set_breakpoint` at line 11 (swap operation in `simple_test.js`) (L289-305)
3. `start_debugging` with optional `dapLaunchArgs` (L308-333)
4. Poll for stack trace via `waitForStackTrace()` (L354-373): polls every 150ms up to 2500ms deadline
5. 10-second wait (L377) — resilience check for session stability
6. `get_local_variables` (L381-391)
7. Returns `{ success, sessionId, errorMessage }` — never throws, wraps errors in return value

Default `launchArgs` when not `null` and not explicitly set: `{ stopOnEntry: false, justMyCode: true }` (L315-318).

### Test Cases

**`'should successfully debug JavaScript via SSE transport'`** (L430-496, timeout: 60s)
- Starts SSE server, connects via `SSEClientTransport` at `http://localhost:<port>/sse`
- Runs full debug sequence with `{ launchArgs: undefined, stackTraceBeforeLocals: true }`
- Asserts `result.success === true` and `result.sessionId` is defined
- Cleanup: calls `close_debug_session` in `finally` block

**`'should provide stack trace without overriding launch args (stopOnEntry default)'`** (L498-541, timeout: 60s)
- Same server setup flow
- Runs debug sequence with `{ launchArgs: null, stackTraceBeforeLocals: false }` — omits DAP launch args entirely, retrieves stack trace after locals
- Asserts same success conditions

### Dependencies
- `waitForHealthEndpoint` from `./smoke-test-utils.js` — polls HTTP health endpoint
- `parseSdkToolResult` from `./smoke-test-utils.js` — extracts structured data from MCP tool call results
- `@modelcontextprotocol/sdk/client/index.js` — MCP `Client`
- `@modelcontextprotocol/sdk/client/sse.js` — `SSEClientTransport`
- Server binary: `dist/index.js` (must be built before running tests)
- Test fixture: `examples/javascript/simple_test.js` (breakpoint at line 11)

### MCP Tool Names Used
- `create_debug_session`
- `set_breakpoint`
- `start_debugging`
- `get_stack_trace`
- `get_local_variables`
- `close_debug_session`
