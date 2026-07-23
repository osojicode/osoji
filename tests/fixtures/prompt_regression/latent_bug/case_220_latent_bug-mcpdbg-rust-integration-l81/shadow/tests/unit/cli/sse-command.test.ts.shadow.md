# tests\unit\cli\sse-command.test.ts
@source-hash: b87d3b5ac761e32b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## Purpose
Unit tests for `createSSEApp` and `handleSSECommand` from `src/cli/sse-command.ts`. Validates SSE endpoint setup, session lifecycle, CORS middleware, health check, graceful shutdown, and signal handling. Mocks `express`, `@modelcontextprotocol/sdk/server/sse.js`, and `src/server.js`.

## Test Structure

### Top-Level Mocks (L10-16)
- `vi.mock('../../../src/server.js')` — mocks `DebugMcpServer`
- `vi.mock('@modelcontextprotocol/sdk/server/sse.js')` — mocks `SSEServerTransport`
- `vi.mock('express')` — mocks entire express module
- `MockedSSEServerTransport` (L16) — typed reference to the vitest-mocked constructor

### Shared Fixtures (L26-82)
- `mockLogger` — WinstonLogger-shaped object with `error/warn/info/debug` spies and `level: 'info'`
- `mockServer` — DebugMcpServer mock with `start`, `stop`, and `server.connect` async stubs
- `mockServerFactory` — vi.fn returning `mockServer`
- `mockExitProcess` — vi.fn spy for process.exit injection
- `fakeProc` — `FakeCurrentProcess` instance; signal handlers attach here instead of real `process` (comment references issues #159/#183)
- `mockTransport` (L57-73) — created per-SSEServerTransport construction; has `sessionId`, `close`, `onclose`, `onerror`, `handlePostMessage`, plus test helpers `triggerClose()` / `triggerError()`

## Test Suites

### `createSSEApp` (L84-156)
- Express app mock set up in nested `beforeEach` with `mockApp.use/get/post/listen`
- Verifies: app creation (L100-108), CORS middleware behavior (L110-138) — OPTIONS vs non-OPTIONS paths, route registration for `/sse` GET+POST and `/health` (L140-148), `sseTransports` Map exposed on app (L150-155)

### `GET /sse route handler` (L158-363)
Helper `setupGetRoute` (L159-197) creates isolated express mock, calls `createSSEApp`, extracts the `/sse` GET handler, and creates EventEmitter-based `req` with `headers/query`.

Key tests:
- Successful connection (L199-219): transport created, stored in `sseTransports`, ping interval fires at 30s
- Server factory throw (L221-228): error propagates out of `setupGetRoute`
- `server.connect` rejection (L230-240): logs error, sends 500
- Transport `onclose` (L242-258): removes from map, does NOT call `mockServer.stop`
- Client disconnect via `req.emit('close')` (L260-278): same cleanup, listener removed
- Recursive close prevention (L280-298): multiple triggers produce single log entry
- Transport `onerror` (L300-311): logs error with session ID
- `headersSent=true` guard (L313-324): skips `res.status`/`res.end` on connection error
- Multiple concurrent connections (L326-350): 3 sessions in map, individual close removes only target
- Ping interval cleared when session removed from map (L352-362)

### `POST /sse route handler` (L365-522)
Nested `beforeEach` re-creates express mock and extracts POST `/sse` handler.

Key tests:
- Valid session ID (L400-424): directly inserts `{transport, server}` into `sseTransports`, calls `transport.handlePostMessage`
- Invalid session ID (L426-450): warns with diagnostic context, returns 400 JSON-RPC error `{code: -32600}`
- Missing session ID (L452-463): warns `hasSessionId: false`, returns 400
- `handlePostMessage` Error rejection (L465-494): returns 500 JSON-RPC `{code: -32603, data: message}`
- Non-Error rejection (L496-521): `data: 'Unknown error'`

### `Health check endpoint` (L524-585)
Extracts `/health` GET handler; tests empty state (L553-563) and active sessions (L565-584).

### `handleSSECommand` (L587-839)
Inner `mockServer` shadow (L588-594) holds `{close, on}` for the HTTP server (shadows outer DebugMcpServer mock).

Key tests:
- Successful start (L597-641): sets `logger.level`, logs startup messages, calls `listen(4000, cb)`, registers SIGINT on `fakeProc`
- Stdin-end with `MCP_EXIT_ON_STDIN_CLOSE=1` (L643-685): issue #122; resumes stdin, on 'end' calls `sharedDebugServer.stop()` + `httpServer.close()` + `exitProcess(0)`
- Server start failure (L687-707): express throws → logs error, calls `exitProcess(1)`
- Port parsing (L709-738): string `'3001'` → integer `3001` passed to `listen`
- SIGINT graceful shutdown (L740-792): closes all transport sessions, calls `sharedDebugServer.stop()`, closes HTTP server, calls `exitProcess(0)`. Uses `fakeProc.lastListener('SIGINT')` to await async handler
- `exitProcess` fallback (L794-810): if not provided, uses `fakeProc.exit`
- Log level unchanged if not provided (L812-838)

### `Server factory options` (L841-873)
Verifies `createSSEApp` passes `{logLevel, logFile}` to serverFactory on GET request.

### `Transport event assignment` (L875-898)
Verifies `mockTransport.onclose` and `mockTransport.onerror` are set after GET handler runs.

## Key Patterns
- **Session map shape**: `sseTransports.set(sessionId, { transport, server })` — tests directly manipulate this map
- **Signal handler isolation**: All tests use `FakeCurrentProcess` to avoid polluting real `process.on`
- **Async close idempotency**: `triggerClose()` / `req.emit('close')` multiple times → single cleanup log
- **Fake timer usage**: Tests using ping interval wrap in `vi.useFakeTimers()` / `vi.useRealTimers()` with cleanup in `afterEach`
- **`MockedSSEServerTransport.mockImplementation`** (L56-73): resets `mockTransport` variable on each construction; tests in POST suite that need a pre-existing transport must manually insert into `sseTransports` (see L403-416 comment explaining test independence concern)
