# src\proxy\dap-proxy-interfaces.ts
@source-hash: 555ef3761380e1ec
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:55Z

## Purpose
Defines all core interfaces, types, and enums for the DAP (Debug Adapter Protocol) Proxy system. Serves as the central contract file enabling dependency injection, testability, and IPC message typing across the proxy subsystem.

## Message Types (IPC Commands: Parent → Worker)

- **`ProxyInitPayload`** (L12–36): `cmd: 'init'` — Session initialization. Carries session ID, executable path, adapter host/port, log dir, script info, breakpoints, and optional `adapterCommand` for language-agnostic spawning. `language` field is optional for backward compatibility with legacy payloads that infer policy from `adapterCommand`.
- **`DapCommandPayload`** (L38–49): `cmd: 'dap'` — Forwards a DAP command to the adapter. Includes `requestId`, `dapCommand`, optional `dapArgs`, `sessionId`, and optional per-request `timeoutMs` override (default: 30s, see Issue #142).
- **`TerminatePayload`** (L51–54): `cmd: 'terminate'` — Signals worker shutdown.
- **`ParentCommand`** (L56): Union type of all three command payloads; discriminated by `cmd` field.

## Response/Event Types (Worker → Parent)

- **`ProxyMessage`** (L60–64): Base message with `type` discriminant (`'status' | 'dapResponse' | 'dapEvent' | 'error'`) and `sessionId`.
- **`StatusMessage`** (L66–73): Adapter lifecycle status (started, exited). Carries process `code`, `signal`, `command`, `script`.
- **`DapResponseMessage`** (L75–82): Result of a DAP request. Correlates via `requestId`; includes `success`, optional `body`, raw `response`, and `error`.
- **`DapEventMessage`** (L84–88): Forwarded DAP event with `event` name and `body`.
- **`ErrorMessage`** (L90–93): Fatal/unexpected proxy error with `message`.

## Core Abstractions (Dependency Injection Interfaces)

- **`ILogger`** (L100–105): Standard logger interface (`info`, `error`, `debug`, `warn`).
- **`IFileSystem`** (L110–113): Async FS ops — `ensureDir`, `pathExists`.
- **`IProcessSpawner`** (L118–120): Wraps `child_process.spawn` for testability.
- **`IDapClient`** (L125–138): Full DAP client contract — `connect()`, `sendRequest<T>()`, `disconnect()`, `shutdown(reason?)` (idempotent), EventEmitter-style `on/off/once/removeAllListeners`.
- **`IDapClientFactory`** (L143–145): Factory creating `IDapClient` instances given host, port, and optional `AdapterPolicy`.
- **`IMessageSender`** (L150–152): IPC send abstraction — single `send(message)` method.
- **`ILoggerFactory`** (L157–159): Callable interface `(sessionId, logDir) => Promise<ILogger>` for delayed logger initialization.

## Configuration Types

- **`AdapterConfig`** (L166–173): Adapter spawn config: executable path, host, port, log dir, optional cwd/env.
- **`AdapterSpawnResult`** (L178–181): Spawn outcome with `ChildProcess` and `pid`.

## State Management

- **`ProxyState`** (L188–194): Enum for proxy worker state machine — `UNINITIALIZED → INITIALIZING → CONNECTED → SHUTTING_DOWN → TERMINATED`.
- **`TrackedRequest`** (L199–204): In-flight request metadata: `requestId`, `command`, `timer` (timeout handle), `timestamp`.
- **`IRequestTracker`** (L209–214): Interface for managing in-flight DAP requests — `track`, `complete`, `clear`, `getPending()`.

## Worker Dependency Bundle

- **`DapProxyDependencies`** (L221–227): Aggregates all five injectable dependencies needed by `DapProxyWorker`: `loggerFactory`, `fileSystem`, `processSpawner`, `dapClientFactory`, `messageSender`.

## DAP Extensions

- **`ExtendedInitializeArgs`** (L234–244): Extends `DebugProtocol.InitializeRequestArguments` with mandatory fields: `clientID`, `clientName`, `adapterID`, `pathFormat: 'path'`, line/column start flags, `supportsVariableType`, `supportsRunInTerminalRequest`, `locale`.

## Key Architectural Decisions
- All abstractions use interfaces (no classes) to maximize testability and mock-ability.
- `ParentCommand` union with `cmd` discriminant supports clean exhaustive dispatch in the worker.
- `ProxyMessage` uses index signature `[key: string]: unknown` for open-ended payload extensibility while keeping base fields typed.
- `IDapClient` mirrors `MinimalDapClient` (noted at L122) — changes to that class must stay in sync.
