# src\index.ts
@source-hash: ebdee7a5744ef6c3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:04Z

## Primary Purpose
Entry point for the Debug MCP Server. Handles critical pre-import console silencing, process setup, CLI wiring, and conditional auto-start. Also exports the public API surface for testing and library use.

## Critical Initialization Order (L7–34)
Before any imports, an IIFE unconditionally:
1. Sets `process.env.CONSOLE_OUTPUT_SILENCED = '1'` (L14)
2. Replaces all console methods (`log`, `error`, `warn`, `info`, `debug`, `trace`, `dir`, `table`, `group`, `groupEnd`, `time`, `timeEnd`, `assert`) with no-ops (L16–29)
3. Removes and suppresses all `process.on('warning', ...)` handlers (L32–33)

This prevents stdout/stderr pollution from corrupting the MCP stdio protocol or IPC channels.

## Argument Sanitization (L37–39)
`process.argv` is rewritten in-place to strip surrounding quotes from all string arguments using regex `/^["'](.*)["']$/`.

## Container Startup Breadcrumb (L74–89)
Module-level `try` block: if `process.env.MCP_CONTAINER === 'true'`, writes an ISO timestamp + argv snapshot to `/app/logs/bundle-start.log` (both `mkdirSync` and `appendFileSync` failures are silently swallowed). Provides diagnostic traces without console output.

## `createDebugMcpServer` (L66–68)
Factory function exported for testing/library use. Accepts `ServerOptions` (`logLevel?`, `logFile?`) and returns `new DebugMcpServer(options)`.

## `main()` (L92–137)
Async entry function:
1. Creates logger `'debug-mcp:cli'` (L93)
2. Stamps `process.env.MCP_DEBUGGER_MAIN_PID` with current PID (L98) — consumed by Java adapter and JVM reaper
3. Calls `reapOrphanJvms({ selfPid, logger })` (L104) — best-effort, never blocks startup
4. Calls `setupErrorHandlers({ logger })` (L113)
5. Creates CLI via `createCLI(...)` with name, description, version (L116)
6. Registers four commands: stdio, SSE, HTTP, check-rust-binary (L119–133), each wiring a setup function to its handler with `{ logger, serverFactory: createDebugMcpServer }`
7. Calls `await program.parseAsync()` (L136)

## Main Module Detection (L141–158)
IIFE `isMainModule` handles both CJS (`require.main === module`) and ESM (`import.meta.url` vs `process.argv[1]`) contexts, with a fallback of `true`. Checks if `scriptPath.endsWith('dist/index.js')` as a broad CJS bundled match.

## Auto-start Gate (L160–168)
If `isMainModule` is true AND `process.env.DEBUG_MCP_SKIP_AUTO_START !== '1'`, calls `main()`. Errors are caught and swallowed (console is silenced); process exits with code 1.

## Exports (L172–183)
Re-exports for testing: `setupErrorHandlers`, `createCLI`, `setupStdioCommand`, `setupSSECommand`, `setupHttpCommand`, `setupCheckRustBinaryCommand`, `handleStdioCommand`, `handleSSECommand`, `handleHttpCommand`, `handleCheckRustBinaryCommand`.

## Key Architectural Decisions
- Console silencing is unconditional and happens before module evaluation of any imported code — this is enforced by being the first executable code in the IIFE before all `import` statements are hoisted/executed (TypeScript compiles imports to top, but the IIFE runs before any of them matter since it's at module level before import side-effects).
- `createDebugMcpServer` decouples server instantiation from CLI commands, enabling test injection.
- JVM orphan reaping on startup ensures clean state after crashes.
- `DEBUG_MCP_SKIP_AUTO_START=1` allows the module to be imported in tests without starting the server.