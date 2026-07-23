# src\cli\sse-command.ts
@source-hash: 7d96a942426488aa
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:28Z

## SSE Command Module (`src/cli/sse-command.ts`)

Implements the deprecated SSE (Server-Sent Events) transport mode for the Debug MCP Server. Provides an Express application factory and a top-level command handler that starts an HTTP server supporting SSE-based MCP communication.

### Key Interfaces

**`ServerFactoryOptions` (L10-13)**
Options forwarded to the `DebugMcpServer` factory: `logLevel` and `logFile` (both optional strings).

**`SSECommandDependencies` (L15-23)**
Dependency injection bag for the SSE command:
- `logger`: Winston logger instance
- `serverFactory`: factory producing a `DebugMcpServer` from `ServerFactoryOptions`
- `exitProcess`: optional process-exit override (defaults to `proc.exit`)
- `stdin`: injectable stdin stream for testing
- `proc`: injectable process-like handle for signals/env/exit (defaults to global `process`)

**`SessionData` (L25-28)** — internal
Stores per-session SSE transport with an `isClosing` guard flag to prevent re-entrant close handling.

---

### `createSSEApp` (L30-193)

Factory that builds and returns a configured Express application. Creates a **single shared `DebugMcpServer`** instance for all SSE connections (line 38-41).

**Routes:**

- **`GET /sse` (L60-133)**: Establishes SSE connection.
  - **Phantom reconnect guard (L67-71)**: If `sharedDebugServer.server.transport` is already set, returns HTTP 204 to permanently close the EventSource (prevents eventsource@4.0.0 auto-reconnect overwriting the active transport).
  - Creates `SSEServerTransport('/sse', res)` and connects to shared server via `sharedDebugServer.server.connect(transport)`.
  - Stores session in `sseTransports` Map keyed by `transport.sessionId`.
  - Sends `:ping\n\n` keep-alives every 30 seconds (L87-93).
  - `closeHandler` (L96-114): idempotent close guard via `isClosing` flag; cleans up interval and map entry; does NOT stop the shared server.
  - Registers `closeHandler` on `transport.onclose`, `req.on('close')`, and `req.on('end')`.

- **`POST /sse` (L136-176)**: Routes client-to-server messages.
  - Reads `sessionId` from `req.query.sessionId`.
  - Returns JSON-RPC 400 error for unknown/missing session; 500 on exception.
  - Delegates to `transport.handlePostMessage(req, res)`.

- **`GET /health` (L179-186)**: Returns `{ status, mode, connections, sessions }` JSON.

**Side effect (L189-190):** Attaches `sseTransports` and `sharedDebugServer` as dynamic properties on the `app` object for use by `handleSSECommand`'s graceful shutdown logic. Uses `any` cast with eslint-disable comments.

---

### `handleSSECommand` (L195-283)

Top-level async command handler. Orchestrates full server lifecycle:

1. Resolves `proc` (L199), `exitProcess` (L200), sets logger level (L202-204).
2. Logs deprecation warning (L207-210): SSE is deprecated; recommends switching to `mcp-debugger http -p <port>`.
3. Creates Express app via `createSSEApp` (L214), extracts `sharedDebugServer` from app's dynamic property (L217), calls `sharedDebugServer.start()` (L218).
4. Calls `app.listen(port)` (L220).
5. Handles `EADDRINUSE` and generic server errors (L225-232).
6. **Graceful shutdown** (`gracefulShutdown`, L236-264): idempotent (guarded by `shutdownStarted` flag). Closes all SSE transports, stops shared debug server, closes HTTP server, calls `exitProcess(0)`.
7. Registers `gracefulShutdown` on `SIGINT` and `SIGTERM` (L266-267).
8. Calls `watchStdinForParentExit` (L273-279) with optional stdin injection for orphan self-defense when `MCP_EXIT_ON_STDIN_CLOSE=1` env var is set.

---

### Architectural Patterns

- **Shared server model**: One `DebugMcpServer` is created for all SSE sessions; individual transport lifecycle does not destroy the shared server.
- **Phantom reconnect protection**: Unique to SSE mode; not needed in HTTP/stdio modes.
- **Dependency injection**: All external dependencies (logger, process, stdin, factory) are injectable for testability.
- **`any` cast for cross-function data sharing**: `sseTransports` and `sharedDebugServer` are attached to the Express app object to share state between `createSSEApp` and `handleSSECommand` without a dedicated wrapper object.
- **Deprecation**: SSE mode is explicitly deprecated in favor of the `http` command.