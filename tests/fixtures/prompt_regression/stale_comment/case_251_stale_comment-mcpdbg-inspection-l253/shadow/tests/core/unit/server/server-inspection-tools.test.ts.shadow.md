# tests\core\unit\server\server-inspection-tools.test.ts
@source-hash: 94130963a0523620
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:07Z

## Purpose
Unit tests for server-side variable inspection and stack trace tools (`get_variables`, `get_stack_trace`, `get_scopes`) exposed by `DebugMcpServer`. Verifies tool handler routing, parameter validation, session lifecycle checks, and error surfacing behavior.

## Structure
Single `describe` block "Server Inspection Tools Tests" (L25–372) containing three nested `describe` blocks for the three inspection tools. All tests share a common `beforeEach`/`afterEach` setup that:
1. Activates fake timers (L33)
2. Builds mock dependencies via `createMockDependencies()` (L35) and stubs `createProductionDependencies` (L36)
3. Creates a mock MCP `Server` instance (L38–39)
4. Creates a mock `StdioServerTransport` (L41–42)
5. Creates a mock `SessionManager` (L44–45)
6. Instantiates `DebugMcpServer` to trigger handler registration (L47)
7. Extracts `callToolHandler` from the mock server via `getToolHandlers` (L48)

`afterEach` (L51–65) clears timers, restores real timers, clears all mocks, and calls `mockSessionManager.closeAllSessions()` if available.

## Tool Handlers Under Test

### `get_variables` (L67–180)
- **Happy path** (L68–99): mocks `getSession` returning active session + `getVariables` resolving with 2 items; asserts `success:true`, `variables`, `count`, and `variablesReference` in JSON response.
- **Missing scope** (L101–122): expects `McpError` with `InvalidParams` code and message matching `/missing.*required.*parameter/i` when `scope` argument is absent.
- **Invalid scope type** (L124–143): passes `scope: 'invalid'` (string); `getVariables` rejects with a runtime error; expects the rejection to propagate as `/Cannot read properties of undefined/`.
- **Session not found** (L145–179): `getSession` returns `null`; normalizes thrown error into `{success:false, error}` shape; asserts error contains `'Session not found: test-session'`.

### `get_stack_trace` (L182–306)
- **Happy path** (L183–208): mocks session with `proxyManager.getCurrentThreadId` returning `1`; `getStackTrace` resolves with 1 frame; asserts `success:true`, `stackFrames` length 1.
- **Missing session** (L210–239): `getSession` returns `null`; normalizes thrown error; asserts `success:false`, error contains `'Session not found: non-existent'`.
- **Null proxy manager** (L241–257): session exists but `proxyManager` is `null`; asserts `success:false`, error contains `'no active proxy for session test-session'`.
- **Missing thread ID** (L259–280): `getCurrentThreadId` returns `null`; asserts same `'no active proxy for session test-session'` error — null thread ID is treated identically to null proxy manager.
- **SessionManager rejection** (L282–305): `getStackTrace` rejects with `'Stack trace failed'`; asserts `success:false`, error contains the real message (regression guard for issue #124 — no silent empty success).

### `get_scopes` (L308–371)
- **Happy path** (L309–335): session active, `getScopes` resolves with 1 scope item; asserts `success:true`, `scopes` length 1.
- **Session not found** (L337–370): `getSession` returns `null`; normalizes error; asserts `success:false`, error contains `'Session not found: test-session'`.

## Key Patterns
- **Error normalization pattern** (L149–172, L213–233, L341–364): try/catch that wraps a handler call and reshapes thrown `McpError` into `{success:false, error}` JSON content — used when the server throws instead of returning an error payload.
- **Issue #124 regression guard** (L282–305): explicit test ensuring DAP-level failures produce `success:false` rather than an empty-but-successful stack trace response.
- **`callToolHandler` extraction**: `getToolHandlers(mockServer).callToolHandler` (L48) — relies on `server-test-helpers.js` capturing the handler registered via `mockServer.setRequestHandler`.

## Dependencies
| Import | Role |
|---|---|
| `vitest` | Test framework |
| `@modelcontextprotocol/sdk/server/index.js` | `Server` class (mocked) |
| `@modelcontextprotocol/sdk/server/stdio.js` | `StdioServerTransport` (mocked) |
| `@modelcontextprotocol/sdk/types.js` | `McpError`, `McpErrorCode` for assertion |
| `../../../../src/server.js` | `DebugMcpServer` — system under test |
| `../../../../src/session/session-manager.js` | `SessionManager` (mocked) |
| `../../../../src/container/dependencies.js` | `createProductionDependencies` (mocked) |
| `./server-test-helpers.js` | `createMockDependencies`, `createMockServer`, `createMockSessionManager`, `createMockStdioTransport`, `getToolHandlers` |
