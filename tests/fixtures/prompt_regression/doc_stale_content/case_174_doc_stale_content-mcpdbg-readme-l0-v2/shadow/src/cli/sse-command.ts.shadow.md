# src\cli\sse-command.ts
@source-hash: 7d96a942426488aa
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:37Z

## SSE Command Handler for MCP Debug Server

Implements the SSE (Server-Sent Events) transport mode for the MCP debug server. Creates an Express application with SSE endpoints and orchestrates server lifecycle including graceful shutdown, CORS, ping keepalives, and orphan-process self-defense.

### Key Exports

#### `ServerFactoryOptions` (L10-13)
Interface for options passed to the server factory function: optional `logLevel` and `logFile` strings.

#### `SSECommandDependencies` (L15-23)
Dependency injection interface for testability:
- `logger`: Winston logger instance
- `serverFactory`: factory producing a `DebugMcpServer`
- `exitProcess`: optional override for `process.exit`
- `stdin`: injectable stdin stream (defaults to `proc.stdin`)
- `proc`: injectable process handle for signals/env/exit (defaults to global `process`)

#### `SessionData` (L25-28, internal)
Internal interface holding a `SSEServerTransport` and an `isClosing` guard flag to prevent recursive close handling.

---

### `createSSEApp(options, dependencies)` (L30-193)

Builds and returns an Express application with:

1. **Shared server instance** (L38-41): One `DebugMcpServer` is created for all connections via `serverFactory`. Stored on `app.sharedDebugServer` (L190) for access by `handleSSECommand`.

2. **CORS middleware** (L48-57): Adds `Access-Control-Allow-Origin: *`, allows GET/POST/OPTIONS, handles preflight with 204.

3. **GET `/sse`** (L60-133): SSE endpoint for server→client messages.
   - **Phantom reconnection guard** (L67-71): If `sharedDebugServer.server.transport` already exists, returns HTTP 204 to permanently stop EventSource reconnection (per SSE spec). Prevents duplicate sessions overwriting the active transport.
   - Creates `SSEServerTransport('/sse', res)` and connects to the shared server (L74-77).
   - Stores `SessionData` in `sseTransports` map keyed by `transport.sessionId` (L82).
   - **30-second ping interval** (L87-93): Writes `:ping\n\n` to keep connection alive; clears itself if session is removed.
   - **`closeHandler`** (L96-114): Guards against double-close with `session.isClosing`. Clears ping interval, removes from map, logs cleanup. Does NOT stop the shared server.
   - Wires `transport.onclose`, `req.on('close')`, and `req.on('end')` all to `closeHandler` (L116-120).
   - Error handler logs transport errors (L123-125).

4. **POST `/sse`** (L136-176): Client→server messages.
   - Extracts `sessionId` from query parameter (L139).
   - Returns JSON-RPC 400 error for unknown/missing sessions (L141-157).
   - Delegates to `transport.handlePostMessage(req, res)` (L162).
   - Returns JSON-RPC 500 on unexpected errors (L166-174).

5. **GET `/health`** (L179-186): Returns `{ status, mode: "sse", connections, sessions }`.

6. **Side-channel properties** (L189-190): Attaches `sseTransports` and `sharedDebugServer` to the app object via `any` casts for use in `handleSSECommand`.

---

### `handleSSECommand(options, dependencies)` (L195-284)

Top-level async entrypoint for the `sse` CLI subcommand:

1. Resolves `proc` (L199), sets log level (L202-204).
2. Emits deprecation warning directing users to `mcp-debugger http` (L207-210).
3. Calls `createSSEApp` then starts the shared debug server via `sharedDebugServer.start()` (L217-218).
4. Listens on parsed `port` (L220-223).
5. Handles `EADDRINUSE` and generic server errors (L225-232), calling `exitProcess(1)`.
6. **Graceful shutdown** (L235-264): Idempotent via `shutdownStarted` flag. Closes all SSE transports, stops shared debug server, then closes HTTP server and calls `exitProcess(0)`.
7. Registers `SIGINT`/`SIGTERM` on `proc` (L266-267).
8. **Stdin watchdog** (L273-279): Calls `watchStdinForParentExit` for orphan self-defense when `MCP_EXIT_ON_STDIN_CLOSE=1` is set (issue #122).

---

### Architectural Notes

- **Single shared `DebugMcpServer`**: Unlike per-connection server models, one server instance serves all SSE clients. The phantom reconnection guard (L67-71) enforces at most one active SSE connection at a time.
- **`any` cast for app properties** (L189-190, 217, 243, 251): Type-unsafe side-channel between `createSSEApp` and `handleSSECommand`. A typed wrapper type would be cleaner.
- **SSE deprecation**: The command logs a deprecation warning on every start (L207-210), indicating users should migrate to the `http` subcommand.
- **Dependency injection pattern**: All I/O and process handles are injectable for test isolation.