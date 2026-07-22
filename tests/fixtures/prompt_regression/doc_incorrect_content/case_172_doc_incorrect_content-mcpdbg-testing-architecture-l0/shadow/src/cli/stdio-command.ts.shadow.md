# src\cli\stdio-command.ts
@source-hash: e34770426cfc07d5
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:21Z

## Purpose
Implements the stdio transport command handler for the Debug MCP Server. Wires together the MCP server, `StdioServerTransport`, and process lifecycle management (keep-alive interval, stdin EOF detection, signal handling, container-mode exception).

## Key Symbols

### `ServerFactoryOptions` interface (L7–10)
Options passed to the `serverFactory` injection: `logLevel?: string`, `logFile?: string`.

### `StdioCommandDependencies` interface (L12–20)
Dependency-injection bag for `handleStdioCommand`:
- `logger` — Winston logger instance
- `serverFactory` — factory that creates a `DebugMcpServer`; receives `ServerFactoryOptions`
- `exitProcess?` — override for `proc.exit(code)` (default derived from `proc` at L27)
- `stdin?` — injectable `NodeJS.ReadStream`; defaults to `proc.stdin` (L73)
- `proc?` — injectable `ProcessLike`; defaults to global `process` (L26)

### `handleStdioCommand(options, dependencies)` async function (L22–116)
Main entry point. Execution flow:
1. Resolves `proc` (L26) and destructures dependencies with `exitProcess` defaulting to `proc.exit` (L27).
2. Optionally sets `logger.level` from `options.logLevel` (L29–31).
3. Calls `serverFactory` to create `DebugMcpServer` (L37–40).
4. Creates `StdioServerTransport` (L44) and a 60-second keep-alive `setInterval` (L47) to prevent the event loop from draining if stdin closes in container mode.
5. Connects server to transport via `debugMcpServer.server.connect(transport)` (L51).
6. Hooks `transport.onclose` via undocumented MCP SDK property (cast at L56); on close: clears keep-alive and calls `exitProcess(0)` (L57–61). **Note:** comment at L55 acknowledges this relies on an undocumented SDK property.
7. Calls `debugMcpServer.start()` (L64).
8. Attaches `transport.onerror` for error logging (L68–70).
9. Resumes `stdin` (L74) to keep the process alive.
10. Registers `stdin.on('end', ...)` (L82–90): exits unless `proc.env.MCP_CONTAINER === 'true'` (container mode — see issue #122, Windows orphan-process concern).
11. Registers `SIGTERM` and `SIGINT` handlers (L93–102): clear keep-alive and exit.
12. Registers `proc.on('exit', ...)` (L103–110): logs diagnostic info (code, argv, env, uptime).
13. On any error in setup, logs and calls `exitProcess(1)` (L111–115).

## Key Design Decisions
- **Container mode** (`MCP_CONTAINER=true`): stdin EOF is intentionally ignored; process stays alive until transport close or signal (reference commit c251b3ff, issue #183).
- **Keep-alive interval** (L47): prevents Node.js event loop from emptying when stdin is gone; cleared in every exit path to avoid process hang.
- **Undocumented SDK hook** (`onclose`, L56): transport close detection relies on an undocumented property; cast to `{ onclose?: () => void }` to avoid type errors.
- **No console output in catch block** (L113 comment): console writes during stdio mode corrupt the MCP binary transport protocol; only file-logger output is safe.

## Dependencies
- `winston` — logger type
- `@modelcontextprotocol/sdk/server/stdio.js` — `StdioServerTransport`
- `../server.js` — `DebugMcpServer`
- `./setup.js` — `StdioOptions` (options shape from CLI setup)
- `../interfaces/process-interfaces.js` — `ProcessLike` (injectable process abstraction)