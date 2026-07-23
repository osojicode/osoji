# src\cli\stdin-watchdog.ts
@source-hash: 5003e51c5d5cf82d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:14Z

## Stdin Watchdog — Orphan Self-Defense for Network-Mode Servers

Implements opt-in parent-death detection via stdin pipe monitoring (issue #122). When `MCP_EXIT_ON_STDIN_CLOSE=1` is set, the server watches for stdin EOF/close/error events to detect supervisor death — particularly useful on Windows where dying parents do not deliver SIGINT/SIGTERM to child processes.

### Key Design Decisions
- **Strictly opt-in** (L11–13): must not exit when stdin is a TTY or closed fd (e.g., `nohup ... < /dev/null`). Guard checked at L48–51.
- **One-shot trigger** (L53–56): `triggered` boolean prevents double-firing across `end`, `close`, and `error` events that may all fire on a broken pipe.
- **Backstop timer** (L63–64): `setTimeout(() => exitProcess(0), backstopMs)` with `.unref()` ensures force-exit if graceful shutdown stalls, without keeping the event loop alive on its own.
- **Stream resume** (L79): `stdin.resume()` is mandatory — a stream in paused/non-flowing mode never emits EOF, so the watchdog would be silently inert without it.
- **Injectable dependencies** (L19–30): accepts `stdin`, `logger`, `shutdown`, `exitProcess`, `backstopMs`, and `env` — all injected for testability. Defaults to `process.env` and `DEFAULT_BACKSTOP_MS = 5000` (L17, L45–46).

### Constants & Interface
- `STDIN_CLOSE_ENV_VAR = 'MCP_EXIT_ON_STDIN_CLOSE'` (L15) — exported env var name used as feature gate.
- `DEFAULT_BACKSTOP_MS = 5000` (L17) — internal fallback timeout before force-exit.
- `StdinWatchdogOptions` (L19–30) — exported interface with required `stdin`, `logger`, `shutdown`, `exitProcess` and optional `backstopMs`, `env`.

### Main Function: `watchStdinForParentExit` (L38–82)
- **Returns** `true` if watchdog was installed, `false` if env gate is off.
- Registers listeners on `end` (L75), `close` (L76), and `error` (L77) events.
- On trigger: logs warning (L57–59), starts backstop timer (L63–64), calls `shutdown()` wrapped in a void promise (L65–72). Shutdown errors are caught and logged; backstop ensures eventual exit.
- Caller is responsible for ensuring `shutdown()` eventually calls `exitProcess` or exits the process; the backstop is a safety net only.

### Usage Pattern
Intended to be called once at server startup in network-mode. The returned boolean can be used to log whether watchdog is active.