# tests\core\unit\server\server-control-tools.test.ts
@source-hash: a523dd3489277c4d
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:30Z

## Purpose
Unit tests for server-side debugging control tools: `set_breakpoint`, `start_debugging`, step operations (`step_over`, `step_into`, `step_out`), `continue_execution`, `pause_execution`, and `list_threads`. Tests validate MCP tool handler behavior including success paths, error handling, and edge cases.

## Test Architecture
- **Setup (L33-48):** Each test creates mocked dependencies via helper factories, wires `DebugMcpServer` with those mocks, then extracts `callToolHandler` from the mock server's registered tool handlers using `getToolHandlers`.
- **Teardown (L50-52):** `vi.clearAllMocks()` after each test.
- **callToolHandler pattern:** All tool invocations use `{ method: 'tools/call', params: { name: <tool>, arguments: {...} } }` and parse `result.content[0].text` as JSON.

## Key Mock Dependencies
- `createMockDependencies()` → `mockDependencies` (L34)
- `createMockServer()` → `mockServer` (L37); `Server` constructor mocked to return it (L38)
- `createMockStdioTransport()` → mocked `StdioServerTransport` (L40-41)
- `createMockSessionManager(adapterRegistry)` → `mockSessionManager` (L43); `SessionManager` mocked to return it (L44)
- `createProductionDependencies` mocked to return `mockDependencies` (L35)

## Tool Test Groups

### `set_breakpoint` (L54-192)
- **Success (L55-94):** Calls `mockSessionManager.setBreakpoint('test-session', path, 10, undefined, undefined)`, response has `success:true`, `breakpointId:'bp-1'`, message containing file:line.
- **Conditional (L96-132):** Passes `condition:'x > 10'` as 4th arg.
- **suspendPolicy (L134-169):** Passes `'thread'` as 5th arg.
- **Session not found (L171-191):** `getSession` returns `null` → response `success:false`, `error` contains `'Session not found: test-session'` (non-throwing).

### `start_debugging` (L194-295)
- **Success (L195-235):** Calls `startDebugging('test-session', path, args, dapLaunchArgs, undefined, undefined)`.
- **Dry run (L237-272):** `dryRunSpawn:true` passed as 5th arg; response `data.dryRun:true`.
- **Session not found (L274-294):** Non-throwing; response `success:false`, `error` contains session message, `state:'stopped'`.

### Step operations (L297-409)
- **Parameterized success (L298-323):** `it.each` over `[step_over/stepOver/'Stepped over', step_into/stepInto/'Stepped into', step_out/stepOut/'Stepped out']`. Calls corresponding `mockSessionManager[methodName]('test-session')`; checks `message` equals expected string.
- **Session not found errors (L325-345):** Non-throwing pattern; `success:false`.
- **Pending/still-running (L347-381):** When step result has `state:'running'` and `data.pending:true`, response surfaces `pending:true`, `state:'running'`, `message` equals `ErrorMessages.stepStillRunning(5)`, no `location`.
- **Failure responses (L383-408):** When `success:false` from SessionManager, response carries `error:'Not paused'`.

### `continue_execution` (L411-453)
- **Success (L412-434):** Calls `mockSessionManager.continue`; response `message:'Continued execution'`.
- **Session not found (L436-452):** Non-throwing; `success:false`.

### `pause_execution` (L455-515)
- **Success (L456-478):** Calls `pause('test-session', undefined)`.
- **Thread-specific (L480-502):** Calls `pause('test-session', 42)` when `threadId:42` provided.
- **Non-existent session (L504-514):** **Throws `McpError`** (different error pattern from other tools).

### `list_threads` (L517-566)
- **Success (L518-543):** Returns array of `{id, name}` thread objects.
- **Non-existent session (L545-555):** **Throws `McpError`**.
- **Missing sessionId (L557-565):** Throws `'Missing required sessionId'`.

## Notable Patterns
- Most tools use soft error responses (`success:false` with `error` field) for session-not-found, but `pause_execution` and `list_threads` **throw `McpError`** — inconsistent error handling across tool group.
- Comments on non-throwing cases say "The server now returns a success response with error message instead of throwing" (L187, L289, L341, L404, L448), documenting an intentional design change.
- `ErrorMessages.stepStillRunning(5)` (L362, L378) is used directly in test assertions, coupling test to the `ErrorMessages` utility.
- File paths use `expect.stringContaining(...)` matching to tolerate OS path normalization.
