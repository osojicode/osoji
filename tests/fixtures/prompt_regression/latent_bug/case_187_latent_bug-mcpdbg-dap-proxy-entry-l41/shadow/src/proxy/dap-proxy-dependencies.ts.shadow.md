# src\proxy\dap-proxy-dependencies.ts
@source-hash: 8d8756e1545ed64c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:13Z

## Purpose
Production dependency factory for the DAP (Debug Adapter Protocol) Proxy Worker. Wires together real implementations of all injectable interfaces required by `DapProxyDependencies`.

## Key Exports

### `createProductionDependencies` (L23-61)
Factory function returning a fully assembled `DapProxyDependencies` object. Accepts an optional `proc` parameter (default: global `process`) that controls IPC/stdout routing — addresses issue #183 for injectable process handle.

Assembled dependencies:
- **`loggerFactory`** (L27-33): `ILoggerFactory` — async factory creating a file-based `debug`-level logger at `<logDir>/proxy-<sessionId>.log` via `createLogger`.
- **`fileSystem`** (L38-41): Thin wrappers over `fs-extra`'s `ensureDir` and `pathExists`.
- **`processSpawner`** (L43-45): Passes through Node's `child_process.spawn` directly.
- **`dapClientFactory`** (L47-49): Creates `MinimalDapClient` instances; cast to `any` due to type compatibility issues between `MinimalDapClient` and `IDapClient`.
- **`messageSender`** (L51-59): Sends messages via `proc.send` (IPC channel) if available, otherwise falls back to `proc.stdout.write` with JSON serialization + newline delimiter.

### `createConsoleLogger` (L66-73)
Returns a minimal `ILogger` implementation backed by `console.log`/`console.error`. Intended for pre-initialization error reporting before the file logger is set up.

**Note:** `debug` and `warn` levels both route to `console.error` (L70-71) — this is likely intentional for stderr visibility but may be surprising.

## Dependencies
- `child_process.spawn` — process spawning
- `fs-extra` (`fs`) — filesystem operations (`ensureDir`, `pathExists`)
- `path` — log file path construction
- `MinimalDapClient` (`./minimal-dap.js`) — concrete DAP client implementation
- `createLogger` (`../utils/logger.js`) — structured file logger factory
- `DapProxyDependencies`, `ILogger`, `ILoggerFactory` (`./dap-proxy-interfaces.js`) — interface contracts
- `ProcessLike` (`../interfaces/process-interfaces.js`) — injectable process abstraction

## Architectural Notes
- This file is the **composition root** for DAP proxy dependencies, separating production wiring from business logic to enable testability via dependency injection.
- The `proc` parameter pattern allows test code to inject a mock process, avoiding direct coupling to the global `process` object.
- The `as any` cast on `MinimalDapClient` (L48) is a known type-compatibility workaround, documented with an ESLint disable comment.