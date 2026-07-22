# src\utils\logger.ts
@source-hash: 460d778e1c606f4d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:36Z

## Purpose
Winston-based logger factory for the Debug MCP Server. Manages per-namespace logger creation, shared file transport caching (to prevent duplicate handles/rotation issues on Windows), per-pid log file naming, stale log cleanup, and container vs. host path selection.

## Key Exports

### `LoggerOptions` interface (L14-19)
Config shape for `createLogger`:
- `level?: string` — log level (error/warn/info/debug); defaults to `DEBUG_MCP_LOG_LEVEL` env var or `'info'`
- `file?: string` — optional explicit log file path; if omitted, uses per-pid default or container path

### `cleanupStaleLogFiles(logDir, opts)` (L82-116)
Best-effort deletion of per-pid log files (matching `PID_LOG_PATTERN`: `/^debug-mcp-server-(\d+)\.log$/`) left by dead processes. Guards:
- Skips current process pid and any live pid (uses `process.kill(pid, 0)` via injectable `SignalFn`)
- Skips files newer than `maxAgeMs` (default: 7 days / `STALE_LOG_MAX_AGE_MS`)
- Ignores legacy fixed-name and proxy log files (pattern mismatch)
- All filesystem errors are swallowed
- Runs at most once per process (`staleLogCleanupDone` flag, L51/L187-190)

### `createLogger(namespace, options)` (L125-236)
Factory that returns a configured `WinstonLoggerType`. Key behaviors:
- **Console transport** (L136-148): Added only when `CONSOLE_OUTPUT_SILENCED !== '1'`. Formats: colorize + timestamp + printf with namespace label.
- **Log file path resolution** (L152-173):
  - Default: `<projectRoot>/logs/debug-mcp-server-<pid>.log` (resolved relative to `import.meta.url` or `process.cwd()`)
  - Container override (`MCP_CONTAINER === 'true'`): `/app/logs/debug-mcp-server.log` (fixed name, single-process container)
  - Explicit `options.file` takes precedence over defaults
- **Log directory creation** (L175-185): `mkdirSync` with `{ recursive: true }` before transport setup
- **Shared `SafeFileTransport` cache** (L192-214): `fileTransportCache` (Map keyed by resolved absolute path, L49) ensures one file handle + rotation counter per path across all loggers in the process. Transport config: `maxsize=50MB`, `maxFiles=3`, `tailable=true`, JSON format.
- **Root logger designation** (L231-233): When `namespace === 'debug-mcp'`, stores logger in module-level `defaultLogger`.
- **Error handler** (L223-228): Logs winston internal transport errors to stderr (unless silenced).

### `getLogger()` (L242-248)
Returns the module-level `defaultLogger`. If not yet set (i.e., `createLogger('debug-mcp', ...)` hasn't been called), creates a fallback logger with namespace `'debug-mcp:default-fallback'` and emits a warn.

## Module-Level State
| Symbol | Type | Purpose |
|---|---|---|
| `defaultLogger` (L21) | `WinstonLoggerType \| null` | Singleton root logger; set when namespace === `'debug-mcp'` |
| `DEFAULT_LOG_BASENAME` (L31) | `string` | `debug-mcp-server-<pid>.log` |
| `PID_LOG_PATTERN` (L34) | `RegExp` | Matches per-pid log filenames for cleanup |
| `STALE_LOG_MAX_AGE_MS` (L37) | `number` | 7 days in ms |
| `fileTransportCache` (L49) | `Map<string, winston.transport>` | Shared file transport pool |
| `staleLogCleanupDone` (L51) | `boolean` | One-shot stale cleanup guard |
| `defaultSignal` (L56) | `SignalFn` | Default process liveness probe via `process.kill` |

## Dependencies
- `winston` — core logging framework
- `./safe-file-transport.js` (`SafeFileTransport`) — custom file transport wrapping winston's rotating file transport (handles Windows rotation edge cases)
- Node built-ins: `path`, `fs`, `url`

## Critical Invariants
- `fileTransportCache` must not be cleared between `createLogger` calls in the same process; doing so would re-create file handles causing Windows rotation failures.
- `staleLogCleanupDone` is never reset; cleanup runs exactly once per process lifetime.
- `logger.close()` is intentionally never called in `src/` (noted at L47) — calling it would close the shared transport for all loggers sharing that file handle.
- Console transport is completely suppressed when `CONSOLE_OUTPUT_SILENCED === '1'` to prevent stdout corruption of MCP JSON-RPC transports.
