# tests\unit\cli\sse-command.test.ts
@source-hash: b87d3b5ac761e32b
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:41Z

## Purpose
Unit test suite for `src/cli/sse-command.ts`, covering `createSSEApp` and `handleSSECommand`. Tests Express app creation, SSE/health route handlers, session lifecycle, signal handling, and graceful shutdown.

## Test Structure

### Top-level describe: `SSE Command Handler` (L18–899)
Shared fixtures set up in `beforeEach` (L26–74):
- `mockLogger`: Winston-compatible fake with `error/warn/info/debug` vi.fn() methods (L28–34)
- `mockServer`: fake `DebugMcpServer` with `start`, `stop`, `server.connect` vi.fn() (L37–43)
- `mockServerFactory`: returns `mockServer` (L46)
- `mockExitProcess`: vi.fn() (L49)
- `fakeProc`: `FakeCurrentProcess` instance for signal isolation (L53)
- `MockedSSEServerTransport`: mocked constructor returning a `mockTransport` with `sessionId`, `close`, `onclose`, `onerror`, `handlePostMessage`, `triggerClose()`, `triggerError()` helpers (L56–73)

`afterEach` clears all timers and mocks (L76–82).

### `createSSEApp` describe (L84–156)
Uses a `mockApp` (L89–95) injected via `vi.mocked(express).mockReturnValue`.

- **L100–108**: Verifies returned app has `get`, `post`, `listen` methods.
- **L110–138**: Verifies CORS middleware behavior — sets `Access-Control-Allow-*` headers and sends 200 for OPTIONS; calls `next()` for non-OPTIONS.
- **L140–148**: Verifies routes registered: `GET /sse`, `POST /sse`, `GET /health`.
- **L150–155**: Verifies `app.sseTransports` is a `Map` instance.

### `GET /sse route handler` describe (L158–363)
Uses local `setupGetRoute()` helper (L159–197) that creates a fresh `expressApp`, calls `createSSEApp`, extracts the GET `/sse` handler, and returns `{ appInstance, getHandler, req, res, expressApp }`. `req` is an `EventEmitter` with `headers` and `query`.

Key tests:
- **L199–219**: SSE connection setup — verifies `mockServerFactory` called with `{logLevel, logFile}`, `SSEServerTransport` constructed with `/sse`, `server.connect` called, transport added to `sseTransports`, ping interval fires `:ping\n\n` every 30s.
- **L221–228**: Server factory throw propagates out of `createSSEApp`.
- **L230–240**: `server.connect` rejection → logs error, sends HTTP 500.
- **L242–258**: Transport `onclose` → removes from `sseTransports`, logs cleanup, does NOT call `server.stop()`.
- **L260–278**: `req.emit('close')` → same cleanup, removes listener.
- **L280–298**: Recursive/duplicate close is idempotent (fired 4x → single cleanup log).
- **L300–311**: `transport.onerror` → logs error with session ID.
- **L313–324**: Headers-already-sent path: skips `res.status` and `res.end`.
- **L326–350**: Multiple concurrent connections (3 calls) → `sseTransports.size === 3`; closing one reduces to 2.
- **L352–362**: Ping interval skips write when session removed from map (cleared externally).

### `POST /sse route handler` describe (L365–522)
`beforeEach` (L371–398): creates fresh app, extracts `POST /sse` handler, creates `mockReq`/`mockRes`.

- **L400–424**: Valid session ID (manually inserted into `sseTransports`) → `transport.handlePostMessage` called.
- **L426–450**: Invalid session ID → logs warn with diagnostic context, returns JSON-RPC 400 error `{code: -32600}`.
- **L452–463**: Missing session ID → warn with `hasSessionId: false`, 400.
- **L465–494**: `handlePostMessage` rejection → logs error, returns JSON-RPC 500 `{code: -32603, data: 'Message handling failed'}`.
- **L496–521**: Non-Error rejection (`'String error'`) → JSON-RPC 500 with `data: 'Unknown error'`.

### `Health check endpoint` describe (L524–585)
- **L553–563**: No connections → `{status: 'ok', mode: 'sse', connections: 0, sessions: []}`.
- **L565–584**: 2 sessions added to `sseTransports` → `connections: 2, sessions: ['session1','session2']`.

### `handleSSECommand` describe (L587–839)
Uses a **shadowed** `mockServer` (L589–594) as the HTTP server mock (has `close`, `on`).

- **L597–641**: Successful start — sets `logger.level`, logs startup messages, calls `listen(4000, cb)`, registers `SIGINT` on `fakeProc`.
- **L643–685**: `MCP_EXIT_ON_STDIN_CLOSE=1` — `stdin.resume()` called; `stdin.emit('end')` triggers graceful shutdown: calls `sharedDebugServer.stop()`, `httpServer.close()`, `mockExitProcess(0)`.
- **L687–707**: `express()` throws → logs `'Failed to start server in SSE mode'`, calls `mockExitProcess(1)`.
- **L709–738**: Port string `'3001'` parsed to integer `3001` for `listen`.
- **L740–792**: SIGINT graceful shutdown — closes all transport sessions, calls `sharedServer.stop()`, `httpServer.close()`, `mockExitProcess(0)`.
- **L794–810**: No `exitProcess` provided → falls back to `fakeProc.exit(1)`.
- **L812–838**: No `logLevel` in options → logger level unchanged.

### `Server factory options` (L841–873)
Verifies `mockServerFactory` receives `{logLevel, logFile}` from options when GET handler fires.

### `Transport event assignment` (L875–898)
Verifies `mockTransport.onclose` and `mockTransport.onerror` are assigned (not null) after GET handler runs.

## Key Dependencies
- `createSSEApp`, `handleSSECommand` from `src/cli/sse-command.js`
- `FakeCurrentProcess` from `test-utils/mocks/fake-current-process.js` — provides isolated EventEmitter-based signal handling with `listenerCount`, `lastListener`, `exit`, `env`
- `DebugMcpServer` from `src/server.js` (vi.mocked)
- `SSEServerTransport` from `@modelcontextprotocol/sdk/server/sse.js` (vi.mocked)
- `express` (vi.mocked)

## Notable Patterns
- **Signal isolation**: `FakeCurrentProcess` prevents SIGINT/SIGTERM handlers from leaking onto the real `process` (comment at L51–52 references issues #159/#183)
- **Transport map structure**: `sseTransports` maps `sessionId → {transport, server}` (visible via direct insertion at L413–416, L472–475, etc.)
- **Session-independent server lifecycle**: `mockServer.stop` is explicitly asserted NOT called on transport close (L257, L276, L297)
- **JSON-RPC error codes**: -32600 for invalid session, -32603 for internal errors
- **Ping interval**: 30-second interval writing `:ping\n\n` to SSE stream; stops when session absent from map
