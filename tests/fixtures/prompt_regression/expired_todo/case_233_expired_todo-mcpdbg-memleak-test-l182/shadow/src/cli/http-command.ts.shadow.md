# src\cli\http-command.ts
@source-hash: 626f87fc42326b04
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:55Z

## Purpose
Implements the HTTP (Streamable HTTP) transport mode for the Debug MCP Server. Creates a multi-session Express app with per-session `DebugMcpServer` instances and handles lifecycle management including graceful shutdown.

## Key Exports

### `ServerFactoryOptions` (L14-17)
Interface for server factory configuration: optional `logLevel` and `logFile` strings.

### `HttpCommandDependencies` (L19-27)
Dependency injection interface:
- `logger`: Winston logger instance
- `serverFactory`: Factory function producing `DebugMcpServer` instances
- `exitProcess`: Optional exit hook (defaults to `proc.exit`)
- `stdin`: Optional injectable stdin for testing
- `proc`: Optional `ProcessLike` for signals/env/exit (defaults to global `process`)

### `SessionData` (L29-32) — internal interface
Associates a `StreamableHTTPServerTransport` with its `DebugMcpServer` for session tracking.

### `createHttpApp(options, dependencies)` (L34-170)
Builds and returns the configured Express app. Key behaviors:
- **L41**: Uses `createMcpExpressApp()` (SDK helper that wires host-header validation)
- **L43**: `httpSessions: Map<string, SessionData>` tracks live sessions
- **L47-63**: CORS middleware — allows all origins, exposes `Mcp-Session-Id`, `Last-Event-Id`, `Mcp-Protocol-Version`; handles OPTIONS preflight
- **L65**: JSON body parser with 10 MB limit
- **L67-151**: `handleMcpRequest` — core dispatcher:
  - **L74-76**: Routes to existing session by `Mcp-Session-Id` header
  - **L77-118**: New session path — only when no session ID + POST + `isInitializeRequest`. Creates isolated `DebugMcpServer` + `StreamableHTTPServerTransport`, connects them, and registers `onsessioninitialized`/`onclose`/`onerror` callbacks
  - **L119-134**: Rejects with JSON-RPC `400` if session is unknown and request is not an initialize
  - **L136**: Delegates to `transport.handleRequest(req, res, req.body)`
- **L153-155**: Routes `POST /mcp`, `GET /mcp`, `DELETE /mcp` to `handleMcpRequest`
- **L157-164**: `GET /health` — returns `{ status, mode: 'http', connections, sessions[] }`
- **L167**: Attaches `httpSessions` map to the app object as a side-channel for `handleHttpCommand` to retrieve (uses `as any` cast)

### `handleHttpCommand(options, dependencies)` (L172-249)
Entry point invoked by CLI. Key behaviors:
- **L176-177**: Resolves `proc` (defaults to global `process`) and `exitProcess`
- **L179-181**: Applies `logLevel` from options to logger
- **L183**: Parses `options.port` to integer
- **L187**: Calls `createHttpApp` and extracts `httpSessions` via the side-channel cast (L189)
- **L191-194**: Starts HTTP server listening on port; logs endpoints
- **L196-203**: Handles `EADDRINUSE` and other server errors; calls `exitProcess(1)`
- **L205-230**: `gracefulShutdown` — idempotent (guards with `shutdownStarted` flag); closes all transports, stops all debug servers, clears session map, closes HTTP server, calls `exitProcess(0)`
- **L232-233**: Registers `SIGINT`/`SIGTERM` handlers on `proc`
- **L239-245**: Calls `watchStdinForParentExit` for opt-in orphan self-defense (controlled by `MCP_EXIT_ON_STDIN_CLOSE` env var, issue #122)

## Architecture Notes
- **Per-session isolation**: Each MCP session gets its own `DebugMcpServer` instance, created on initialize and destroyed on close.
- **Transport lifecycle**: `onsessioninitialized` callback is used to map the SDK-assigned session ID → session data after transport construction. The `createdTransport` forward-declaration pattern (L87-98) is necessary because `onsessioninitialized` fires before `newTransport` is assigned in the outer scope.
- **Side-channel pattern**: `httpSessions` map is attached to the Express app as `(app as any).httpSessions` (L167) so `handleHttpCommand` can access it without refactoring `createHttpApp`'s return type.
- **Shutdown idempotency**: `shutdownStarted` flag (L205) prevents double-shutdown from concurrent stdin/signal events.
