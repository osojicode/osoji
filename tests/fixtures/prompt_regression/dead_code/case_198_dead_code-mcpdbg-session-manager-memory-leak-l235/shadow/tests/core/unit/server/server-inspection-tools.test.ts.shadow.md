# tests\core\unit\server\server-inspection-tools.test.ts
@source-hash: 35a9dba9139b0d31
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:39Z

## Purpose
Unit tests for server-side variable and stack inspection MCP tools: `get_variables`, `get_stack_trace`, and `get_scopes`. Verifies tool handler behavior including success paths, parameter validation, session-not-found errors, and DAP-level failure propagation.

## Test Structure

### Suite: `Server Inspection Tools Tests` (L25–371)
Top-level describe block containing all inspection tool tests. Uses `beforeEach`/`afterEach` for mock setup/teardown.

### Setup Pattern (L31–49)
- `beforeEach`: Activates fake timers, wires all mocked modules, instantiates `DebugMcpServer`, and extracts `callToolHandler` via `getToolHandlers(mockServer).callToolHandler`
- `afterEach` (L51–65): Clears timers, restores real timers, clears all mocks, and calls `mockSessionManager.closeAllSessions()` if available

### Mocked Modules
- `@modelcontextprotocol/sdk/server/index.js` — `Server`
- `@modelcontextprotocol/sdk/server/stdio.js` — `StdioServerTransport`
- `../../../../src/session/session-manager.js` — `SessionManager`
- `../../../../src/container/dependencies.js` — `createProductionDependencies`

## Tool Tests

### `get_variables` (L67–179)
| Test | Description |
|------|-------------|
| `should get variables successfully` (L68–99) | Happy path: mocks `getSession` returning ACTIVE session, `getVariables` returning 2 vars. Asserts `success:true`, `variables.length==2`, `count==2`, `variablesReference==100` |
| `should validate required scope parameter` (L101–122) | Missing `scope` arg → expects `McpError` with `InvalidParams` code and message matching `/missing.*required.*parameter/i` |
| `should validate scope parameter type` (L124–143) | `scope: 'invalid'` (string instead of number) → `getVariables` rejects with property-read error → test expects `rejects.toThrow(/Cannot read properties of undefined/)` |
| `should handle SessionManager errors` (L145–178) | `getSession` returns null → expects `success:false` with `'Session not found: test-session'` |

### `get_stack_trace` (L181–305)
| Test | Description |
|------|-------------|
| `should get stack trace successfully` (L182–207) | Session with `proxyManager.getCurrentThreadId()→1`, `getStackTrace` returns 1 frame → `success:true`, `stackFrames.length==1` |
| `should handle missing session` (L209–238) | `getSession→null` → `success:false`, error contains `'Session not found: non-existent'` |
| `should handle missing proxy manager` (L240–256) | `proxyManager: null` → `success:false`, error contains `'no active proxy for session test-session'` |
| `should handle missing thread ID` (L258–279) | `getCurrentThreadId()→null` → `success:false`, same error as missing proxy manager |
| `should surface SessionManager errors as a truthful tool-level failure` (L281–304) | `getStackTrace` rejects → `success:false` with real error message (guards against issue #124: empty-but-successful stack trace) |

### `get_scopes` (L307–370)
| Test | Description |
|------|-------------|
| `should get scopes successfully` (L308–334) | ACTIVE session, `getScopes` returns 1 scope → `success:true`, `scopes.length==1` |
| `should handle SessionManager errors` (L336–369) | `getSession→null` → `success:false`, error contains `'Session not found: test-session'` |

## Key Patterns
- All tool calls use `callToolHandler({ method: 'tools/call', params: { name: '<tool>', arguments: {...} } })`
- Response shape: `{ content: [{ text: JSON.stringify({success, ...}) }] }`
- Error-handling tests use try/catch to normalize both thrown errors and success-with-error-object responses
- Fake timers used to avoid real timeout side effects during test execution
- `getToolHandlers` helper from `server-test-helpers.js` extracts registered handler from mock server

## Notable Constraints
- `get_stack_trace` requires a session with a non-null `proxyManager` AND a non-null thread ID from `getCurrentThreadId()`
- Issue #124 is explicitly referenced: DAP failures must yield `success:false`, never silently empty responses
- Parameter validation for `get_variables` enforces presence of `scope` at the MCP layer before reaching `SessionManager`