# src\cli\stdio-command.ts
@source-hash: e34770426cfc07d5
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:50Z

## Purpose
Implements the stdio transport command handler for the Debug MCP Server. Manages server lifecycle, transport connection, process signal handling, stdin EOF detection, and graceful shutdown — all routed through injectable dependencies for testability.

## Key Exports

### `ServerFactoryOptions` (L7-10)
Interface for options passed to the server factory function:
- `logLevel?: string` — optional log verbosity override
- `logFile?: string` — optional log file path

### `StdioCommandDependencies` (L12-20)
Dependency injection interface for `handleStdioCommand`:
- `logger` — Winston logger instance
- `serverFactory` — factory producing `DebugMcpServer` instances
- `exitProcess?` — override for `process.exit`; defaults to `proc.exit(code)`
- `stdin?` — injectable `ReadStream`; defaults to `proc.stdin`
- `proc?` — injectable `ProcessLike` handle; defaults to global `process`

### `handleStdioCommand` (L22-116)
Async function that:
1. Resolves `proc` from dependencies or global `process` (L26)
2. Optionally overrides `logger.level` from `options.logLevel` (L29-31)
3. Creates `DebugMcpServer` via `serverFactory` (L37-40)
4. Creates `StdioServerTransport` (L44)
5. Sets a `setInterval` keep-alive timer (60s, no-op) to prevent event loop from draining (L47)
6. Connects server to transport via `debugMcpServer.server.connect(transport)` (L51)
7. Hooks `transportWithClose.onclose` via an undocumented SDK property (cast: L56-61) — clears keep-alive, calls `exitProcess(0)`
8. Starts the debug server via `debugMcpServer.start()` (L64)
9. Attaches `transport.onerror` error logging handler (L68-70)
10. Resumes `stdin` to keep process alive (L74)
11. Handles `stdin 'end'` event (L82-90): exits cleanly unless `MCP_CONTAINER=true` env var is set (container mode: waits for transport close/signal instead)
12. Handles `SIGTERM` (L93-97), `SIGINT` (L98-102): clears keep-alive, exits
13. Handles `proc 'exit'` (L103-110): logs diagnostics (argv, env, uptime)
14. On any startup error: logs and calls `exitProcess(1)` (L111-115)

## Architecture & Patterns
- **Full dependency injection**: logger, serverFactory, exitProcess, stdin, proc — all injectable, enabling unit testing without real processes or servers.
- **Keep-alive interval**: A no-op `setInterval` (L47) prevents Node.js from exiting when stdin is the only pending handle. Must be cleared on every exit path.
- **`onclose` undocumented SDK property**: Cast `transport` to `{ onclose?: () => void }` (L56) to hook transport close. Documented as relying on an undocumented MCP SDK property — fragile, may break on SDK upgrades.
- **Container mode (`MCP_CONTAINER=true`)**: Stdin EOF is ignored in container deployments where stdin may close spuriously (L83-86). Reference to commit c251b3ff and issue #122.
- **Protocol safety**: Error path never writes to console (L113 comment) to avoid corrupting the stdio MCP transport protocol.

## Dependencies
- `winston` — Logger type (type-only import)
- `@modelcontextprotocol/sdk/server/stdio.js` — `StdioServerTransport`
- `../server.js` — `DebugMcpServer`
- `./setup.js` — `StdioOptions` (input options shape)
- `../interfaces/process-interfaces.js` — `ProcessLike` (injectable process abstraction)
