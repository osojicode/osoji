# tests\unit\cli\http-command.test.ts
@source-hash: 710b72cbfc58444f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:18Z

## Purpose
Unit tests for the `createHttpApp` and `handleHttpCommand` functions from `src/cli/http-command.ts`. Validates HTTP MCP server creation, session management, request routing, CORS middleware, graceful shutdown, and the stdin watchdog feature.

## Test Structure

### Top-level suite: `HTTP Command Handler` (L17–565)
All tests share `beforeEach`/`afterEach` setup blocks (L30–96).

**Shared fixtures:**
- `mockLogger` (L31–37): Winston-compatible mock with `error`, `warn`, `info`, `debug` spies
- `mockServer` (L39–45): Mock `DebugMcpServer` with `start`, `stop`, `server.connect` spies
- `mockServerFactory` (L47): vi.fn returning `mockServer`
- `mockExitProcess` (L48): vi.fn for process exit
- `fakeProc` (L51): `FakeCurrentProcess` instance — signal handlers attach here, never real `process`
- `MockedStreamableHTTPServerTransport` (L55–78): Factory that creates transport stubs with `triggerSessionInit()`, `triggerClose()`, `triggerError()` helpers; pushes each to `createdTransports[]`
- `mockApp` (L80–88): Express app mock with spies on `use`, `get`, `post`, `delete`, `all`, `listen`; returned by `mockedCreateMcpExpressApp`

**afterEach** (L91–96): `vi.unstubAllEnvs()`, `vi.clearAllTimers()`, `vi.useRealTimers()`, `vi.clearAllMocks()`

---

### `createHttpApp` suite (L98–150)

| Test | Lines | What it checks |
|------|-------|----------------|
| Creates Express app via SDK helper (DNS rebind protection) | L99–102 | `mockedCreateMcpExpressApp` was called |
| Exposes `httpSessions` Map for graceful shutdown | L104–110 | `app.httpSessions` is a `Map` instance |
| Registers `/mcp` on POST, GET, DELETE | L112–117 | All three HTTP methods registered |
| Registers `/health` endpoint | L119–122 | GET `/health` registered |
| Installs CORS middleware with correct headers | L124–149 | `Access-Control-Allow-Origin: *`, exposes `Mcp-Session-Id`, `Last-Event-Id`, `Mcp-Protocol-Version`; OPTIONS returns 200 without calling `next` |

---

### `/mcp request handling` suite (L152–352)

**Helpers:**
- `getHandler()` (L153–159): Creates app, extracts the POST `/mcp` handler function
- `makeReq(overrides)` (L162–168): Builds a minimal request object
- `makeRes()` (L170–177): Builds a minimal response mock with `status` (chainable), `json`, `end`, `headersSent`

| Test | Lines | What it checks |
|------|-------|----------------|
| New transport+server created for `initialize` without session ID | L179–203 | `mockServerFactory` called once, transport created once, `server.connect` called; `triggerSessionInit()` → session added to `httpSessions` map |
| Known `Mcp-Session-Id` routes to existing transport | L206–233 | Second request with session ID does NOT create new transport/server; routes to `firstTransport.handleRequest` |
| Non-initialize POST without session ID → 400 | L235–252 | No transport created; response is JSON-RPC error with code `-32600` |
| Unknown `Mcp-Session-Id` → 400 | L254–268 | Same JSON-RPC error response |
| Transport close removes session + stops server | L270–287 | `triggerClose()` → session removed from map; `mockServer.stop` called (async via `setImmediate`) |
| Transport errors are logged | L289–305 | `triggerError(err)` → `mockLogger.error` called with session ID in message |
| `handleRequest` throws → 500 when headers not sent | L307–329 | Overrides transport with rejecting `handleRequest`; expects `res.status(500)` |
| `handleRequest` throws → no status when headers already sent | L331–351 | `res.headersSent = true`; expects `res.status` NOT called |

---

### `/health endpoint` suite (L354–382)

| Test | Lines | What it checks |
|------|-------|----------------|
| Reports `mode: 'http'` and session count | L355–381 | Empty map → `{status:'ok', mode:'http', connections:0, sessions:[]}`; after inserting session → `connections:1, sessions:['s1']` |

---

### `handleHttpCommand` suite (L384–565)

`mockHttpServer` (L385–392): Has `close` (calls callback) and `on` spies.

| Test | Lines | What it checks |
|------|-------|----------------|
| Starts server on parsed port, logs endpoint URL | L394–413 | `listen(4000, cb)` called; `logger.info` contains `http://localhost:4000/mcp`; `logger.level` set to `'debug'`; signal handlers registered on `fakeProc` |
| App creation failure → exits code 1 | L416–429 | `mockedCreateMcpExpressApp` throws → `logger.error('Failed to start server in HTTP mode')` + `exitProcess(1)` |
| SIGINT closes all transports/servers, then exits 0 | L431–463 | `fakeProc.lastListener('SIGINT')()` awaited; all transport `close()` and server `stop()` called; `mockHttpServer.close` called; `exitProcess(0)` |
| `EADDRINUSE` error → specific log message + exit 1 | L541–564 | HTTP server `error` event with `code: 'EADDRINUSE'` → logger contains 'already in use'; `exitProcess(1)` |

**stdin watchdog sub-suite** (L465–539) — tests `MCP_EXIT_ON_STDIN_CLOSE` env gate (issue #122):
- `makeFakeStdin()` (L466–473): Creates `EventEmitter`-based fake stdin with `resume` spy
- Stdin `end` + env set → graceful shutdown, exits 0; also closes active sessions (L482–505)
- Double-fire (`end` + `close`) triggers shutdown only once (L507–522)
- Env gate unset → `stdin.resume` never called; no exit on `end` event (L524–538)

## Key Mocking Architecture

- `vi.mock('../../../src/server.js')` (L8): `DebugMcpServer` fully mocked
- `vi.mock('@modelcontextprotocol/sdk/server/streamableHttp.js')` (L9): `StreamableHTTPServerTransport` replaced with factory spy
- `vi.mock('@modelcontextprotocol/sdk/server/express.js')` (L10): `createMcpExpressApp` returns `mockApp`
- Transport stubs include `triggerSessionInit()`, `triggerClose()`, `triggerError()` helpers to drive SDK callbacks synchronously from tests
- `FakeCurrentProcess` prevents leaking signal handlers to real `process` (issues #159/#183, L49–50)

## Critical Invariants Tested
1. Session lifecycle: `onsessioninitialized` callback populates `httpSessions`; `onclose` removes + stops server
2. Request routing: `mcp-session-id` header disambiguates new vs. existing sessions
3. Graceful shutdown: closes all transports and servers before calling `exitProcess(0)`
4. Idempotent shutdown: stdin watchdog fires at most once regardless of `end`/`close` event ordering
