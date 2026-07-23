# tests\unit\cli\stdio-command.test.ts
@source-hash: 5e11758bca46c0b2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:18Z

## Unit Tests: `handleStdioCommand` (STDIO CLI Handler)

Tests the `handleStdioCommand` function from `src/cli/stdio-command.ts`, verifying server lifecycle, signal handling, stdin EOF behavior, and dependency injection patterns.

### Test Structure
- **Outer suite**: "STDIO Command Handler" (L10–245)
- **Nested suite**: "stdin EOF handling (issue #122)" (L202–244)

### Fixtures & Setup (L17–54)
- `makeFakeStdin()` (L17–24): Creates an `EventEmitter`-backed fake `NodeJS.ReadStream` with a mocked `.resume()` method. Used to simulate stdin events (notably `'end'`).
- `beforeEach` (L26–54): Initializes:
  - `mockLogger`: Partial Winston logger mock (`error`, `warn`, `info`, `debug`, mutable `level`)
  - `mockServer`: Fake `DebugMcpServer` with `server.connect` (resolves), `start` (resolves), `stop` (resolves)
  - `mockServerFactory`: `vi.fn()` returning `mockServer`
  - `mockExitProcess`: `vi.fn()` standing in for `process.exit`
  - `fakeProc`: `FakeCurrentProcess` instance — receives all signal/exit listeners, isolating tests from real `process`
- `afterEach` (L56–60): Emits `SIGTERM` on `fakeProc` to exercise and clear the 60s keep-alive interval registered by `handleStdioCommand` (prevents timer leaks between tests).

### Test Cases

| Test | Lines | Key Assertions |
|---|---|---|
| Successful server start | L62–96 | `logger.level` set to `'debug'`; `logger.info` called with start/success messages; `serverFactory` called with `{ logLevel, logFile }`; `server.start` called; `exitProcess` NOT called |
| Signal listener registration | L98–121 | `fakeProc` has exactly 1 listener each for `SIGTERM`, `SIGINT`, `exit`; `SIGINT` triggers `exitProcess(0)`; `exit` event triggers `logger.error('[MCP] Process exiting', { code, argv, uptime })` |
| No log level change without option | L123–143 | `mockLogger.level` stays `'warn'`; `serverFactory` called with `{ logLevel: undefined, logFile: undefined }` |
| Server start failure | L145–164 | `server.start` rejects → `logger.error('Failed to start server in stdio mode', { error })`; `exitProcess(1)` |
| Fallback to `proc.exit` without `exitProcess` | L166–180 | When `exitProcess` not injected, `fakeProc.exit` called with `1` on start failure |
| Server factory throws | L182–200 | Factory throwing → same error log + `exitProcess(1)` |
| stdin EOF exits 0 in host mode | L203–223 | `stdin.resume()` called; `stdin.emit('end')` → `exitProcess(0)` + `logger.warn` containing `'MCP client disconnected'` |
| stdin EOF ignored in container mode | L225–243 | `fakeProc.env.MCP_CONTAINER = 'true'`; `stdin.emit('end')` → `exitProcess` NOT called; `logger.warn` containing `'ignoring in container mode'` |

### Dependency Injection Contract
`handleStdioCommand` accepts an options bag and a deps object with:
- `logger`: Winston-compatible logger
- `serverFactory`: Factory returning a `DebugMcpServer`-shaped object
- `exitProcess` (optional): Exit function; falls back to `proc.exit`
- `stdin` (optional): Readable stream for EOF detection
- `proc`: Process handle (signal/exit listeners, `env`, `argv`, `uptime`)

### Module Mock
- `'../../../src/server.js'` is fully mocked via `vi.mock` (L8), so `DebugMcpServer` is only used as a type reference for `mockServer`.

### Notable Patterns
- **Issue references**: `#122` (stdin EOF), `#159`/`#183` (signal isolation via `FakeCurrentProcess`)
- **Timer cleanup**: `afterEach` SIGTERM emission is specifically designed to clear the keep-alive interval held in `handleStdioCommand`'s closure, preventing test timer leaks.
- **Container mode toggle**: Set via `fakeProc.env.MCP_CONTAINER = 'true'` (L226), exercising environment-variable-driven branching in the SUT.
