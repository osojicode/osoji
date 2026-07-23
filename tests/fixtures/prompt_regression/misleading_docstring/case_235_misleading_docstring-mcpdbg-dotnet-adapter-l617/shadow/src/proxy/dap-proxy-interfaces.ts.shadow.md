# src\proxy\dap-proxy-interfaces.ts
@source-hash: 555ef3761380e1ec
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:56Z

## Overview

Pure type/interface definitions file for the DAP (Debug Adapter Protocol) Proxy system. Defines the complete contract surface for IPC messaging, dependency injection abstractions, state management, and DAP protocol extensions. No runtime logic — consumed by the proxy worker, adapter manager, and test infrastructure.

## Message Types (IPC Commands — Parent → Proxy)

- **`ProxyInitPayload`** (L12–36): `cmd: 'init'` message to initialize a debug session. Key fields: `sessionId`, `language?` (optional, falls back to `adapterCommand`-based inference for legacy payloads), `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath`, `scriptArgs?`, `stopOnEntry?`, `justMyCode?`, `initialBreakpoints?`, `dryRunSpawn?`, `launchConfig?`, `adapterCommand?` (language-agnostic adapter spawning with `command`, `args`, `env`).
- **`DapCommandPayload`** (L38–49): `cmd: 'dap'` message to forward a DAP command. Fields: `requestId`, `dapCommand`, `dapArgs?`, `sessionId`, `timeoutMs?` (per-request override; default 30s per Issue #142).
- **`TerminatePayload`** (L51–54): `cmd: 'terminate'` with optional `sessionId`.
- **`ParentCommand`** (L56): Union type of the three command payloads.

## Response/Event Types (Proxy → Parent)

- **`ProxyMessage`** (L60–64): Base interface with `type`, `sessionId`, and open index signature.
- **`StatusMessage`** (L66–73): `type: 'status'` — lifecycle status with optional `code`, `signal`, `command`, `script`.
- **`DapResponseMessage`** (L75–82): `type: 'dapResponse'` — carries `requestId`, `success`, optional `body`, full `DebugProtocol.Response`, and `error` string.
- **`DapEventMessage`** (L84–88): `type: 'dapEvent'` — forwarded adapter events with `event` name and `body`.
- **`ErrorMessage`** (L90–93): `type: 'error'` — error notification with `message`.

## Core Abstractions (Dependency Injection Interfaces)

- **`ILogger`** (L100–105): Standard four-level logger (`info`, `error`, `debug`, `warn`).
- **`IFileSystem`** (L110–113): Minimal FS abstraction — `ensureDir(path)` and `pathExists(path)`.
- **`IProcessSpawner`** (L118–120): Wraps `child_process.spawn`; returns `ChildProcess`.
- **`IDapClient`** (L125–138): Full DAP client contract — `connect()`, `sendRequest<T>(command, args?, timeoutMs?)`, `disconnect()`, `shutdown(reason?)` (idempotent), EventEmitter-style `on/off/once/removeAllListeners`.
- **`IDapClientFactory`** (L143–145): Factory with `create(host, port, policy?)` returning `IDapClient`.
- **`IMessageSender`** (L150–152): Single-method IPC abstraction — `send(message)`.
- **`ILoggerFactory`** (L157–159): Callable interface `(sessionId, logDir) => Promise<ILogger>` for deferred logger initialization.

## Configuration Types

- **`AdapterConfig`** (L166–173): Adapter spawn config — `executablePath`, `host`, `port`, `logDir`, optional `cwd` and `env`.
- **`AdapterSpawnResult`** (L178–181): Spawn outcome — `process: ChildProcess` and `pid: number`.

## State Management

- **`ProxyState`** (L188–194): String enum for proxy worker state machine: `UNINITIALIZED → INITIALIZING → CONNECTED → SHUTTING_DOWN → TERMINATED`.
- **`TrackedRequest`** (L199–204): In-flight request snapshot — `requestId`, `command`, `timer: NodeJS.Timeout`, `timestamp`.
- **`IRequestTracker`** (L209–214): Request lifecycle tracker — `track(requestId, command, timeoutMs?)`, `complete(requestId)`, `clear()`, `getPending(): Map<string, TrackedRequest>`.

## Worker Dependency Bag

- **`DapProxyDependencies`** (L221–227): Aggregates all five DI interfaces needed by `DapProxyWorker`: `loggerFactory`, `fileSystem`, `processSpawner`, `dapClientFactory`, `messageSender`.

## DAP Protocol Extension

- **`ExtendedInitializeArgs`** (L234–244): Extends `DebugProtocol.InitializeRequestArguments` with explicit fields for DAP initialize handshake: `clientID`, `clientName`, `adapterID`, `pathFormat: 'path'`, `linesStartAt1`, `columnsStartAt1`, `supportsVariableType`, `supportsRunInTerminalRequest`, `locale`.

## Architectural Notes

- All interfaces support dependency injection — production and test implementations are swapped at construction time.
- `language?` on `ProxyInitPayload` is intentionally optional for backward compatibility; consumer must handle the absent case by falling back to `adapterCommand`-based policy inference.
- `IDapClient.on/off/once` use `any[]` for handler variadic args (eslint-suppressed) — matches Node.js EventEmitter variance.
- The `timeoutMs` on `DapCommandPayload` (L48) references Issue #142 — per-request override pattern propagated through worker → request tracker → DAP socket layers.