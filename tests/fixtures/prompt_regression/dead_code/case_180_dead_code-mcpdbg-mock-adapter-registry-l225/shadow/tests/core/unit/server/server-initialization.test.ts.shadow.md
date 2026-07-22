# tests\core\unit\server\server-initialization.test.ts
@source-hash: 32f558ba7b76529f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:15Z

## Server Initialization Tests

Unit test suite for `DebugMcpServer` constructor, initialization behavior, and tool handler registration. Tests verify correct wiring between the MCP SDK's `Server`, `StdioServerTransport`, `SessionManager`, and `createProductionDependencies`.

### Test Structure

**Outer suite:** `Server Initialization Tests` (L25–176)

**Setup (L32–44):**
- Creates mock dependencies via `createMockDependencies()` and wires `createProductionDependencies` to return them.
- Mocks `Server` constructor to return `mockServer`.
- Mocks `StdioServerTransport` constructor to return `mockStdioTransport`.
- Mocks `SessionManager` constructor to return `mockSessionManager`.
- `vi.clearAllMocks()` in `afterEach` (L46–48).

### Sub-suites and Key Tests

**`Constructor and Initialization` (L50–111):**
- `should initialize server with correct configuration` (L51–64): Verifies `Server` is called with `{ name: 'debug-mcp-server', version: '0.1.0' }` and capabilities `{ tools: {} }`, and `createProductionDependencies` receives `{ logLevel: 'debug', logFile: undefined, sessionLogDirBase: undefined }`.
- `should initialize with log file configuration` (L66–81): Verifies that when `logFile` is provided, `sessionLogDirBase` is computed as `path.resolve(path.dirname(logFile), 'sessions')`.
- `should handle dependency creation errors` (L83–89): Verifies constructor propagates errors thrown by `createProductionDependencies`.
- `should register tool handlers` (L91–96): Verifies `mockServer.setRequestHandler` is called exactly twice (ListTools + CallTool).
- `should set error handler` (L98–110): Verifies `mockServer.onerror` is defined and invokes `logger.error('Server error', { error })` when called.

**`Tool Handler Registration` (L113–176):**
- `should handle tools/list request` (L114–140): Invokes the `listToolsHandler` extracted by `getToolHandlers`, expects a non-empty tools array containing 15 specific tool names: `create_debug_session`, `list_debug_sessions`, `set_breakpoint`, `start_debugging`, `close_debug_session`, `step_over`, `step_into`, `step_out`, `continue_execution`, `pause_execution`, `get_variables`, `get_stack_trace`, `get_scopes`, `evaluate_expression`, `get_source_context`.
- `should handle unknown tool error` (L142–153): Verifies `callToolHandler` rejects with `'Unknown tool: unknown_tool'` for unrecognized tool names.
- `should handle tool execution errors` (L155–175): Configures `mockSessionManager.createSession` to reject; verifies `callToolHandler` rejects with `/Session creation failed/` and `logger.error` is called with `'Failed to create debug session'`.

### Mocked Modules
- `@modelcontextprotocol/sdk/server/index.js` — `Server` class
- `@modelcontextprotocol/sdk/server/stdio.js` — `StdioServerTransport` class
- `../../../../src/session/session-manager.js` — `SessionManager` class
- `../../../../src/container/dependencies.js` — `createProductionDependencies`

### Helper Utilities (from `server-test-helpers.js`)
- `createMockDependencies()` — builds mock deps including `logger`, `adapterRegistry`
- `createMockServer()` — mock MCP server with `setRequestHandler`, `onerror`
- `createMockSessionManager(adapterRegistry)` — mock session manager with `createSession`
- `createMockStdioTransport()` — mock transport
- `getToolHandlers(mockServer)` — extracts `{ listToolsHandler, callToolHandler }` from registered handlers on `mockServer`

### Critical Invariants
- `Server` constructor must be called with exactly the name `'debug-mcp-server'` and version `'0.1.0'`.
- `setRequestHandler` must be called exactly 2 times (one per handler type).
- `sessionLogDirBase` derivation depends on `path.resolve(path.dirname(logFile), 'sessions')` — platform-specific behavior noted at L73.
