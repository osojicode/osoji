# src\cli\stdin-watchdog.ts
@source-hash: 5003e51c5d5cf82d
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:00Z

## stdin-watchdog.ts

Implements an opt-in "parent death" watchdog for network-mode MCP servers (issue #122). When `MCP_EXIT_ON_STDIN_CLOSE=1` or `=true` is set, installs listeners on stdin to detect EOF/close/error events that indicate the parent/supervisor process has died, then triggers graceful shutdown with a force-exit backstop timer.

### Problem Solved
On Windows, dying parent processes do not deliver SIGINT/SIGTERM to children. By watching for stdin pipe closure (which occurs when the parent dies), this module provides a cross-platform parent-death signal. Strictly opt-in via environment variable to avoid false triggers in standalone/TTY/nohup scenarios.

### Key Symbols

**`STDIN_CLOSE_ENV_VAR` (L15)** — Exported constant `'MCP_EXIT_ON_STDIN_CLOSE'`. The environment variable gate controlling whether the watchdog activates.

**`DEFAULT_BACKSTOP_MS` (L17)** — Internal constant `5000` ms. Force-exit deadline if graceful shutdown stalls.

**`StdinWatchdogOptions` (L19-30)** — Interface defining all dependencies injected into the watchdog:
- `stdin`: Any `NodeJS.ReadableStream` (only `.on()` and `.resume()` used — accepts test fakes)
- `logger`: Object with `warn(msg: string)` method
- `shutdown`: Graceful shutdown callback; may return a Promise
- `exitProcess`: Force-exit callback (typically `process.exit`)
- `backstopMs?`: Override for the 5-second backstop (default: `DEFAULT_BACKSTOP_MS`)
- `env?`: Override for environment (default: `process.env`)

**`watchStdinForParentExit` (L38-82)** — Primary export. Checks the env gate (L48-51); if off, returns `false` immediately. Installs one-shot (`triggered` flag, L53-55) listeners for `'end'`, `'close'`, and `'error'` events on stdin (L75-77). On first trigger: logs a warning (L57-59), arms an `unref`'d backstop `setTimeout` (L63-64), and calls `shutdown()` in a floating promise with error catch (L65-72). Calls `stdin.resume()` (L79) to move the stream out of paused mode so EOF is actually reported. Returns `true` when installed.

### Architectural Decisions
- **Dependency injection**: All I/O side effects (`stdin`, `exitProcess`, `env`) are injected, making the module fully testable without globals.
- **One-shot guard**: `triggered` boolean (L53) prevents duplicate shutdown calls if multiple events fire simultaneously.
- **Unref'd backstop timer**: `backstop.unref?.()` (L64) ensures the timer never artificially keeps the process alive if shutdown completes normally.
- **Floating promise**: `void Promise.resolve().then(() => shutdown())` (L65) handles both sync and async shutdown implementations without blocking the event listener.
- **`stdin.resume()` is required** (L79): Without a `data` listener, Node.js streams stay paused and never emit EOF events.