# tests\core\unit\server\server-redefine-and-attach.test.ts
@source-hash: 6cef649c83437489
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:03Z

## Purpose
Unit tests for `redefine_classes` tool registration/dispatch and `attach`/`stopOnEntry` behavior in `DebugMcpServer`. Validates MCP tool schema correctness, argument forwarding to `SessionManager`, and attach-mode-specific behaviors.

## Test Structure

### Setup (L31–48)
- Uses shared helpers from `server-test-helpers.js` to create mock dependencies, server, transport, and session manager
- Instantiates `DebugMcpServer` and extracts `callToolHandler` and `listToolsHandler` via `getToolHandlers(mockServer)`
- All MCP SDK classes and production dependencies are vitest-mocked

### Test Groups

#### `set_breakpoint on attach sessions` (L54–85)
- **L55**: Verifies attach-mode sessions (`attachMode: true`) bypass the host-side file existence check for remote filesystem paths (e.g., `/app/app.rb`)
- Asserts `setBreakpoint` called with `('attach-session', '/app/app.rb', 18, undefined, undefined)`

#### `redefine_classes tool registration` (L87–110)
- **L88**: Confirms `redefine_classes` appears in `tools/list` response
- **L94**: Validates input schema has required fields `sessionId`, `classesDir` and optional `sinceTimestamp`, `timeout`
- **L104**: Validates `evaluate_expression` schema also exposes `timeout` property

#### `redefine_classes tool dispatch` (L112–258)
- **L113**: Correct argument forwarding: `sessionManager.redefineClasses('test-session', '/path/to/classes', 1000000, undefined)`; response includes `success`, `redefined`, `redefinedCount`, `newestTimestamp`
- **L150**: `sinceTimestamp` defaults to `0` when omitted from arguments
- **L180**: `timeout` argument forwarded as 4th param to `redefineClasses` (tracks issue #142)
- **L212**: `timeout` argument forwarded to `evaluateExpression` as 4th param (issue #142); `frameId` defaults to `undefined`
- **L242**: Rejected promise from `redefineClasses` propagates as thrown error matching `/Session not found/`

#### `create_debug_session attach stopOnEntry` (L260–350)
- `mockSessionInfo` fixture (L261–268): Python session with id `'attach-session-1'`
- **L274**: `stopOnEntry` defaults to `undefined` (not `false`) when not provided — session manager decides behavior
- **L299**: `stopOnEntry: true` is forwarded when explicitly set
- **L325**: `verifyTimeout: 12000` is forwarded to `attachToProcess` (tracks issue #143)

#### `attach_to_process stopOnEntry` (L352–429)
- **L353**: `stopOnEntry` defaults to `undefined` (not `false`) for `attach_to_process` tool
- **L378**: `stopOnEntry: true` forwarded when explicitly set
- **L404**: `verifyTimeout: 12000` forwarded to `attachToProcess` (issue #143)

## Key Dependencies
- `server-test-helpers.js`: Shared mock factory utilities (`createMockDependencies`, `createMockServer`, `createMockSessionManager`, `createMockStdioTransport`, `getToolHandlers`)
- `DebugMcpServer` (production): registers MCP tools and routes `tools/call` to session manager methods
- `SessionManager` (mocked): `redefineClasses`, `evaluateExpression`, `setBreakpoint`, `attachToProcess`, `createSession`, `getSession`, `getSessionPolicy`

## Notable Patterns
- `callToolHandler` invoked with full MCP message shape `{ method: 'tools/call', params: { name, arguments } }`
- Response parsed from `result.content[0].text` as JSON
- `stopOnEntry: undefined` (not `false`) is the intended default — key semantic distinction tested explicitly
- Issue references `#142` (timeout forwarding) and `#143` (verifyTimeout forwarding) embedded in test names