# tests\core\unit\server\server-control-tools.test.ts
@source-hash: a523dd3489277c4d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:05Z

## Server Control Tools Tests

Unit tests for the server-side debugging control tools exposed via MCP (Model Context Protocol). Tests validate tool handlers for breakpoint management, debugging lifecycle control, step operations, continue/pause execution, and thread listing.

### File Structure
- **Single `describe` block**: `Server Control Tools Tests` (L27–567)
- **Setup** (L33–48): Wires mock dependencies, mock `Server`, mock `StdioServerTransport`, mock `SessionManager`, instantiates `DebugMcpServer`, extracts `callToolHandler` via `getToolHandlers(mockServer).callToolHandler`
- **Teardown** (L50–52): `vi.clearAllMocks()`

### Test Groups

#### `set_breakpoint` (L54–192)
- **L55–94**: Happy path — verifies `setBreakpoint('test-session', '/path/to/test.py', 10, undefined, undefined)`, response has `success: true`, `breakpointId: 'bp-1'`, message contains file/line
- **L96–132**: Conditional breakpoint — passes `condition: 'x > 10'` as 4th arg
- **L134–169**: `suspendPolicy` forwarding — passes `'thread'` as 5th arg
- **L171–191**: Error path — `getSession` returns `null` → response `success: false`, error contains `'Session not found: test-session'`

#### `start_debugging` (L194–295)
- **L195–235**: Happy path — verifies `startDebugging` called with `(sessionId, scriptPath, args, dapLaunchArgs, undefined, undefined)`, response has `success: true`, `state: 'running'`
- **L237–272**: Dry run — `dryRunSpawn: true` passed as 5th arg, response `data.dryRun: true`
- **L274–294**: Error path — `getSession` returns `null` → response `success: false`, `state: 'stopped'`

#### `step operations` (L297–409)
Parameterized via `it.each` over `[step_over/stepOver, step_into/stepInto, step_out/stepOut]`:
- **L298–323**: Success — mock returns `{ success: true, state: 'stopped' }`, verifies method called with `sessionId`, response message matches `'Stepped over/into/out'`
- **L325–345**: Error path — `getSession: null` → `success: false`, error contains session not found
- **L347–381**: Pending/still-running case — mock returns `{ success: true, state: 'running', data: { message: ErrorMessages.stepStillRunning(5), pending: true } }` → response propagates `state: 'running'`, `pending: true`, message equals `ErrorMessages.stepStillRunning(5)`, `location` is `undefined`
- **L383–408**: Failure response — mock returns `{ success: false, state: 'error', error: 'Not paused' }` → response `success: false`, `error: 'Not paused'`

#### `continue_execution` (L411–453)
- **L412–434**: Happy path — `continue` mock resolves → response `success: true`, message `'Continued execution'`
- **L436–452**: Error path — `getSession: null` → `success: false`, error contains session not found

#### `pause_execution` (L455–515)
- **L456–478**: Success — `pause('test-session', undefined)` called
- **L480–502**: Thread-specific pause — `threadId: 42` passed → `pause('test-session', 42)`
- **L504–514**: Non-existent session — `getSession: null` → **throws `McpError`** (different error contract from other tools)

#### `list_threads` (L517–566)
- **L518–543**: Success — returns 2 threads, verifies shape `{ id, name }`
- **L545–555**: Non-existent session → **throws `McpError`**
- **L557–565**: Missing `sessionId` → throws `'Missing required sessionId'`

### Key Patterns
- `callToolHandler` is extracted from mock server handlers each `beforeEach`, simulating tool dispatch
- Most tools return structured error responses (`success: false`) rather than throwing; `pause_execution` and `list_threads` throw `McpError` — inconsistent error contract worth noting
- `getSession` mock returning `null` is the primary error trigger for session-not-found scenarios
- `sessionLifecycle: 'ACTIVE'` is required on session objects for lifecycle validation to pass
- `ErrorMessages.stepStillRunning(5)` used as a cross-module message contract value (L362, L378)

### Dependencies
- **`server-test-helpers.js`**: Provides `createMockDependencies`, `createMockServer`, `createMockSessionManager`, `createMockStdioTransport`, `getToolHandlers`
- **`DebugMcpServer`** (`src/server.js`): The system under test — instantiated in beforeEach
- **`SessionManager`** (`src/session/session-manager.js`): Mocked, methods stubbed per test
- **`@debugmcp/shared`**: Provides `Breakpoint` type used in test fixtures
- **`ErrorMessages`** (`src/utils/error-messages.js`): Used for `stepStillRunning` message assertion
