# tests\unit\cli\stdio-command.test.ts
@source-hash: 5e11758bca46c0b2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:16Z

## Purpose
Unit tests for `handleStdioCommand` CLI handler, verifying server lifecycle, signal handling, stdin EOF behavior, error handling, and process injection patterns.

## Test Suite Structure
- **Top-level describe**: `'STDIO Command Handler'` (L10–245)
- **Nested describe**: `'stdin EOF handling (issue #122)'` (L202–244)

## Key Test Fixtures & Setup (L26–54)

### `makeFakeStdin()` (L17–24)
Internal factory that creates an `EventEmitter`-based fake stdin stream with a mocked `resume()` method. Used to simulate stdin lifecycle events (`end`) without touching real process streams.

### `beforeEach` (L26–54)
Sets up per-test mocks:
- `mockLogger`: partial Winston logger with `error`, `warn`, `info`, `debug` mocked via `vi.fn()`, `level: 'info'`
- `mockServer`: fake `DebugMcpServer` with `server.connect`, `start`, `stop` all `vi.fn().mockResolvedValue(undefined)`
- `mockServerFactory`: `vi.fn()` returning `mockServer`
- `mockExitProcess`: `vi.fn()` standing in for `process.exit`
- `fakeProc`: `FakeCurrentProcess` instance — captures signal/exit listeners without touching real process

### `afterEach` (L56–60)
Fires `SIGTERM` on `fakeProc` after each test to clean up the `keepAlive` interval registered inside `handleStdioCommand` (clears the 60s interval, preventing timer leaks).

## Test Cases

| Test | Lines | What is verified |
|---|---|---|
| Successful server start | L62–96 | Logger level set, `info` logs emitted, serverFactory called with correct options, `start()` called, no exit |
| Signal listener registration | L98–121 | SIGTERM/SIGINT/exit each get exactly 1 listener on `fakeProc`; SIGINT calls `exitProcess(0)`; `exit` event logs diagnostics with `argv`, `uptime` from `fakeProc` |
| No log level change without option | L123–143 | Logger level stays `'warn'`; factory called with `logLevel: undefined, logFile: undefined` |
| Server start failure | L145–164 | `start()` rejection → `logger.error('Failed to start server in stdio mode', { error })` → `exitProcess(1)` |
| exitProcess fallback to proc.exit | L166–180 | When `exitProcess` not provided, `fakeProc.exit` is called with `1` on failure |
| Server factory throws | L182–200 | Synchronous factory throw → same error/exit flow as async failure |
| stdin EOF in host mode | L203–223 | `stdin.resume()` called; `stdin.emit('end')` → `exitProcess(0)` + warn log containing `'MCP client disconnected'` |
| stdin EOF in container mode | L225–243 | `fakeProc.env.MCP_CONTAINER = 'true'` → `stdin.emit('end')` ignored; `exitProcess` NOT called; warn log contains `'ignoring in container mode'` |

## Key Architectural Decisions
- **Dependency injection**: `handleStdioCommand` accepts `{ logger, serverFactory, exitProcess, stdin, proc }` overrides — tests never touch real `process` or real server
- **`FakeCurrentProcess`**: Replaces the real process handle for signal/exit event capture; referenced in issues #159/#183
- **`vi.mock('../../../src/server.js')` (L8)**: Auto-mocks the entire server module; concrete mock constructed manually in `beforeEach`
- **Timer cleanup via afterEach SIGTERM**: The 60s keep-alive interval inside `handleStdioCommand` is cleared by firing SIGTERM in `afterEach` — tests implicitly rely on the handler's SIGTERM listener calling `clearInterval`
- **`MCP_CONTAINER` env variable**: Checked on `fakeProc.env` to gate stdin EOF behavior

## Dependencies
- `handleStdioCommand` from `src/cli/stdio-command.js` — the system under test
- `FakeCurrentProcess` from `tests/test-utils/mocks/fake-current-process.js` — process handle mock
- `DebugMcpServer` from `src/server.js` — auto-mocked, type used for `mockServer`
- `vitest`: `describe`, `it`, `expect`, `vi`, `beforeEach`, `afterEach`
- `events.EventEmitter`: base for fake stdin