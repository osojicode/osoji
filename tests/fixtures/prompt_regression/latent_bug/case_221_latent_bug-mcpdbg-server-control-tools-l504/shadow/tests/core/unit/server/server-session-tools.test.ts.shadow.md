# tests\core\unit\server\server-session-tools.test.ts
@source-hash: fa3069be508cd2fb
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:54Z

## Purpose
Unit tests for server-side session management MCP tools: `create_debug_session`, `list_debug_sessions`, and `close_debug_session`. Tests verify tool handler behavior via a mocked `DebugMcpServer` instance.

## Test Setup Pattern (L32–47)
All tests follow the same `beforeEach` setup:
1. Create mock dependencies via `createMockDependencies()` (L33)
2. Mock `createProductionDependencies` to return mocks (L34)
3. Create and inject mock `Server`, `StdioServerTransport`, and `SessionManager` (L36–43)
4. Instantiate `DebugMcpServer` which triggers handler registration (L45)
5. Extract `callToolHandler` from the mock server via `getToolHandlers()` (L46)

The `callToolHandler` is the central testing interface — all tool invocations are dispatched through it with `{ method, params: { name, arguments } }` payloads.

## Tool Tests

### `create_debug_session` (L53–156)
- **Happy path (L54–88):** Calls `mockSessionManager.createSession` with `{ language, name, executablePath }`, expects JSON response with `success: true`, `sessionId`, and message containing `'Created python debug session'`.
- **Invalid language (L90–110):** `'java'` as language should throw `McpError` with message `"Language 'java' is not supported"`. Tested twice to verify both error type and message.
- **SessionManager error (L112–129):** Rejected `createSession` propagates error and logs via `mockDependencies.logger.error` with key `'Failed to create debug session'`.
- **Default name generation (L131–155):** When `name` is omitted, the generated name should match regex `/^python-debug-\d+$/`.

### `list_debug_sessions` (L158–207)
- **Happy path (L159–192):** `mockSessionManager.getAllSessions` returns array of 2 sessions; expects `success: true`, `sessions` array length 2, `count: 2`.
- **Error handling (L194–206):** Synchronous throw from `getAllSessions` propagates as error.

### `close_debug_session` (L209–253)
- **Success (L210–224):** `closeSession` resolves `true`; expects `success: true`, message containing `'Closed debug session'`.
- **Not found (L226–240):** `closeSession` resolves `false`; expects `success: false`, message containing `'Failed to close debug session'`.
- **Error handling (L242–252):** Rejected `closeSession` propagates.

## Key Dependencies
- **`server-test-helpers.js`** (L12–18): Provides all mock factory functions (`createMockDependencies`, `createMockServer`, `createMockSessionManager`, `createMockStdioTransport`, `getToolHandlers`). Central to the test architecture.
- **`@debugmcp/shared`** (L10): Provides `DebugSessionInfo`, `DebugLanguage`, `SessionState` types used for fixture construction.
- **`DebugMcpServer`** (L8): Production class under test; must be instantiated to register tool handlers on the mock server.
- **`SessionManager`** (L9): Mocked at module level (L23); instance methods `createSession`, `getAllSessions`, `closeSession` are the primary mock targets.

## Mocking Strategy
All external modules are mocked at the top level (L21–24) using `vi.mock`. The pattern replaces constructors with mock implementations that return pre-configured mock objects. `vi.clearAllMocks()` runs `afterEach` (L49–51).