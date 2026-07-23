# tests\unit\cli\http-command.test.ts
@source-hash: 710b72cbfc58444f
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:39Z

## Purpose
Unit tests for `createHttpApp` and `handleHttpCommand` from `src/cli/http-command.ts`. Verifies HTTP MCP server lifecycle: Express app creation, `/mcp` route handling (session management, transport creation, error handling), `/health` endpoint, graceful shutdown via SIGINT/SIGTERM, and stdin watchdog behavior.

## Key Structure

### Test Suite: `HTTP Command Handler` (L17-565)
Top-level describe block containing all tests. Sets up shared mocks in `beforeEach` (L30-89), teardown in `afterEach` (L91-96).

### Mock Setup (L30-89)
- `mockLogger` (L31-37): Stub Winston logger with `error`, `warn`, `info`, `debug`, `level`.
- `mockServer` (L39-45): Stub `DebugMcpServer` with `start`, `stop`, `server.connect` (all resolved promises).
- `mockServerFactory` (L47): vi.fn returning `mockServer`.
- `fakeProc` (L51): `FakeCurrentProcess` — captures signal handlers without touching real `process`; references issues #159/#183.
- `MockedStreamableHTTPServerTransport` (L55-78): Mock implementation captures transport options, generates random `sessionId`, exposes test helpers `triggerSessionInit()`, `triggerClose()`, `triggerError(err)`. Pushes each created transport to `createdTransports[]` and sets `mockTransport`.
- `mockApp` (L80-88): Stub Express app with `use`, `get`, `post`, `delete`, `all`, `listen`. `mockedCreateMcpExpressApp` returns this mock.

### `describe('createHttpApp')` (L98-150)
- L99-102: Verifies `createMcpExpressApp` (SDK helper) is called → DNS rebind protection.
- L104-110: Checks returned app has `httpSessions` as a `Map` (for graceful shutdown).
- L112-117: Verifies `/mcp` registered on POST, GET, DELETE.
- L119-122: Verifies `/health` registered on GET.
- L124-149: Tests inline CORS middleware (first `use()` call):
  - Sets `Access-Control-Allow-Origin: *`, exposes `Mcp-Session-Id`, `Last-Event-Id`, `Mcp-Protocol-Version`.
  - OPTIONS short-circuits with `sendStatus(200)` without calling `next`.

### `describe('/mcp request handling')` (L152-352)
Helper functions:
- `getHandler()` (L153-160): Creates app, extracts POST `/mcp` handler.
- `makeReq(overrides)` (L162-168): Constructs minimal request object.
- `makeRes()` (L170-177): Stub response with `status` (chainable), `json`, `end`, `headersSent: false`.

Tests:
- L179-204: Initialize without session ID → creates new transport + server, wires `server.connect(transport)`, checks `onsessioninitialized` and `sessionIdGenerator` options, registers session in `httpSessions` map after `triggerSessionInit()`.
- L206-233: Follow-up POST with known `Mcp-Session-Id` → routes to existing transport, no new transport/server created.
- L235-252: Non-Initialize POST without session ID → 400 + JSON-RPC error `code: -32600`.
- L254-268: POST with unknown `Mcp-Session-Id` → 400 + `code: -32600`.
- L270-287: Transport `onclose` → session removed from map + `server.stop()` called (uses `setImmediate` to wait for async `stop()`).
- L289-305: Transport `onerror` → `logger.error` called with message containing `sessionId` and the error.
- L307-329: `handleRequest` throws, `headersSent: false` → `logger.error` + `res.status(500)`.
- L331-351: `handleRequest` throws, `headersSent: true` → `logger.error` but `res.status` NOT called.

### `describe('/health endpoint')` (L354-382)
- L355-381: Verifies health handler returns `{ status: 'ok', mode: 'http', connections: N, sessions: [...keys] }`. Tests with 0 sessions then 1 injected session.

### `describe('handleHttpCommand')` (L384-565)
- `mockHttpServer` (L385-392): Stub HTTP server with `close` (invokes callback), `on`.

Tests:
- L394-414: Successful start — `listen(4000, cb)` called, `logger.level` set to `'debug'`, logs URL `http://localhost:4000/mcp`, SIGINT/SIGTERM listeners registered on `fakeProc`.
- L416-429: App creation throws → `logger.error('Failed to start server in HTTP mode', {error})` + `exitProcess(1)`.
- L431-463: SIGINT handler — closes all session transports (`t1.close()`, `t2.close()`), stops all servers (`s1.stop()`, `s2.stop()`), closes HTTP server, calls `exitProcess(0)`.
- Stdin watchdog (`MCP_EXIT_ON_STDIN_CLOSE`, issue #122) (L465-539):
  - L482-505: When env var set + stdin emits `'end'` → graceful shutdown runs + `exitProcess(0)`.
  - L507-522: `'end'` then `'close'` → shutdown runs exactly once (idempotent).
  - L524-538: Env var unset → stdin not resumed, no shutdown on `'end'`.
- L541-564: `EADDRINUSE` error event → `logger.error` with "already in use" + `exitProcess(1)`.

## Key Patterns
- **`FakeCurrentProcess`**: Prevents real signal handler registration; `lastListener(signal)` retrieves the registered async handler for direct invocation in tests.
- **`triggerSessionInit()` helper**: Drives SDK's `onsessioninitialized` callback, allowing tests to control when sessions appear in the map.
- **`setImmediate` / `vi.waitFor`**: Used to wait for async `stop()` calls to settle after triggering close/end events.
- **`mockImplementationOnce`**: Overrides transport factory per-test for error scenario tests (L310-318, L333-339).
- **Modules mocked at top level** (L8-10): `src/server.js`, `@modelcontextprotocol/sdk/server/streamableHttp.js`, `@modelcontextprotocol/sdk/server/express.js`.
