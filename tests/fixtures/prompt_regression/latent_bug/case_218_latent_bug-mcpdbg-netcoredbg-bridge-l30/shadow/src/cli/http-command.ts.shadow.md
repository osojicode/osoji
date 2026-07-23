# src\cli\http-command.ts
@source-hash: 626f87fc42326b04
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:41Z

## Purpose
Sets up and runs a Streamable HTTP MCP server using Express. Manages per-session `DebugMcpServer` + `StreamableHTTPServerTransport` pairs, handles CORS, graceful shutdown, and orphan self-defense via stdin watchdog.

## Key Exports

### `ServerFactoryOptions` interface (L14-17)
Options passed to the `serverFactory` function: optional `logLevel` and `logFile`.

### `HttpCommandDependencies` interface (L19-27)
DI container for `handleHttpCommand` and `createHttpApp`:
- `logger`: Winston logger
- `serverFactory`: factory producing a `DebugMcpServer` from `ServerFactoryOptions`
- `exitProcess`: optional override for `process.exit` (defaults to `proc.exit`)
- `stdin`: injectable stdin stream for tests
- `proc`: injectable `ProcessLike` for signals/env/exit (defaults to global `process`)

### `SessionData` interface (L29-32) — internal
Maps a session ID to its `StreamableHTTPServerTransport` + `DebugMcpServer` pair.

---

### `createHttpApp(options, dependencies)` (L34-170)
Builds and returns a configured Express app without starting a listener. Key responsibilities:
- Creates app via `createMcpExpressApp()` (L41) — wires host-header validation
- Installs CORS middleware (L47-63): allows `*` origin; exposes `Mcp-Session-Id`, `Last-Event-Id`, `Mcp-Protocol-Version`; handles `OPTIONS` preflight
- Attaches `express.json` body parser with 10 MB limit (L65)
- Registers `POST /mcp`, `GET /mcp`, `DELETE /mcp` → `handleMcpRequest` (L153-155)
- Registers `GET /health` returning `{ status, mode, connections, sessions }` (L157-164)
- Exposes `httpSessions` map on `(app as any).httpSessions` (L167) for retrieval by `handleHttpCommand`

**`handleMcpRequest` inner function (L67-151):**
Three-way dispatch based on `Mcp-Session-Id` header:
1. **Existing session** (L74-76): header present + found in map → reuse transport
2. **New session** (L77-118): no header + POST + `isInitializeRequest` → create new `DebugMcpServer`, new `StreamableHTTPServerTransport` with `randomUUID` session generator, register `onsessioninitialized` callback that stores session in map, wire `onclose` (deletes from map, stops server) and `onerror` handlers, connect transport to server
3. **Reject** (L119-134): missing/unknown session ID that isn't an initialize request → HTTP 400 JSON-RPC error (code `-32600`)

Error boundary (L137-150): uncaught errors → HTTP 500 JSON-RPC error (code `-32603`) if headers not yet sent.

---

### `handleHttpCommand(options, dependencies)` (L172-249)
Async entry point for the `http` CLI command:
1. Resolves `proc` (L176), logger log level (L179-181), port (L183)
2. Calls `createHttpApp` and retrieves `httpSessions` from the app (L187-189)
3. Starts Express listener (L191-194)
4. Handles `EADDRINUSE` and general server errors → `exitProcess(1)` (L196-203)
5. Registers idempotent `gracefulShutdown` (L206-230): closes all transports, stops all `DebugMcpServer`s, clears session map, closes HTTP server, calls `exitProcess(0)`
6. Binds `SIGINT` / `SIGTERM` to `gracefulShutdown` (L232-233)
7. Calls `watchStdinForParentExit` for orphan detection when `MCP_EXIT_ON_STDIN_CLOSE=1` (L239-245)

## Architecture Notes
- **Per-session isolation**: each MCP client gets its own `DebugMcpServer` + transport; no shared state between sessions.
- **Forward declaration pattern** (L87-98): `createdTransport` is set to `null` before `new StreamableHTTPServerTransport`, then assigned immediately after construction so the `onsessioninitialized` closure captures the correct reference.
- **`(app as any).httpSessions`** (L167, L189): the session map is smuggled from `createHttpApp` to `handleHttpCommand` via a dynamic property on the Express app — avoids a return-tuple or global.
- **Idempotent shutdown guard** (L205-209): `shutdownStarted` boolean prevents duplicate shutdown when stdin close + SIGTERM arrive simultaneously.
