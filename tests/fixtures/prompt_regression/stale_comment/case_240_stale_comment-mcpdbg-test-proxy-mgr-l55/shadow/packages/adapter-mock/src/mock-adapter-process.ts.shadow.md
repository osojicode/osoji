# packages\adapter-mock\src\mock-adapter-process.ts
@source-hash: b65967e4dccf0f9a
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:36Z

## Mock Debug Adapter Process

Entry-point script (`#!/usr/bin/env node`) that implements a fully self-contained DAP (Debug Adapter Protocol) server for testing purposes. Supports both stdio and TCP transport modes. Spawned as a child process by the mock adapter package during tests.

---

### Architecture Overview

Two classes cooperate:
1. **`DAPConnection` (L16-88)** – Low-level DAP framing (HTTP-style `Content-Length` headers over a byte stream). Handles message buffering, parsing, and serialization.
2. **`MockDebugAdapterProcess` (L97-784)** – High-level DAP session logic. Parses CLI args, sets up transport, routes all DAP requests to handlers, and simulates debugger behavior (breakpoints, stepping, threads, variables).

Module-level: `new MockDebugAdapterProcess()` at L787 starts everything immediately on process launch.

---

### `DAPConnection` (L16-88)

| Member | Lines | Description |
|--------|-------|-------------|
| `constructor(input, output)` | L19-22 | Defaults to `process.stdin`/`process.stdout` |
| `start()` | L24-29 | Attaches `data` listener; feeds `messageBuffer` |
| `on(event, handler)` | L31-38 | Registers `'request'` or `'disconnect'` handlers; disconnect binds `end`+`close` on input |
| `sendResponse(response)` | L40-42 | Delegates to `sendMessage` |
| `sendEvent(event)` | L44-46 | Delegates to `sendMessage` |
| `processMessages()` | L50-81 | Parses framed DAP messages; byte-aware split using `Buffer.from` to handle multi-byte UTF-8 correctly |
| `sendMessage(message)` | L83-87 | Serializes to JSON, prepends `Content-Length` header |
| `onRequest` | L48 | Private callback set via `on('request', ...)` |

**Key design**: `messageBuffer` is a string, but byte-length arithmetic uses `Buffer.from(..., 'utf8')` to correctly handle multi-byte characters (L66-70).

---

### `createConnection(input?, output?)` (L90-92)

Factory helper for `DAPConnection`. Internal use only.

---

### `MockDebugAdapterProcess` (L97-784)

**State:**
- `breakpoints: Map<string, DebugProtocol.Breakpoint[]>` (L100) — keyed by file path
- `variableHandles: Map<number, {variables: ...}>` (L101) — keyed by auto-incremented reference IDs
- `nextVariableReference` (L102) — starts at 1000
- `currentLine` (L103) — simulated execution cursor, starts at 1
- `threads` (L104) — static single thread `[{id:1, name:'main'}]`
- `connection?: DAPConnection` (L98)
- `server?: net.Server` (L99)

**Constructor (L106-142):** Parses `--port`, `--host`, `--session` CLI args. If `--port` is given, creates TCP server (`setupTCPServer`); otherwise uses stdio via `createConnection()`.

**Transport setup:**
- `setupTCPServer(host, port)` (L144-171): Creates `net.Server`; each socket becomes a new `DAPConnection`. Exits on server error but NOT on socket close (allows reconnection).
- `setupConnection(connection)` (L173-183): Wires `handleRequest` and disconnect logic. On disconnect in stdio mode, calls `process.exit(0)`.

**Request dispatch — `handleRequest` (L190-261):**
Routes by `request.command` string to typed handler methods:

| Command | Handler | Lines | Behavior |
|---------|---------|-------|----------|
| `initialize` | `handleInitialize` | L263-316 | Returns capability flags, sends `initialized` event |
| `configurationDone` | `handleConfigurationDone` | L318-326 | Simple ACK |
| `launch` | `handleLaunch` | L328-397 | ACK; if `stopOnEntry` → stopped@entry after 100ms; else → first breakpoint or terminated after 200ms |
| `setBreakpoints` | `handleSetBreakpoints` | L399-426 | Stores breakpoints by path, returns verified BPs with random IDs |
| `threads` | `handleThreads` | L428-439 | Returns static `[{id:1, name:'main'}]` |
| `stackTrace` | `handleStackTrace` | L441-476 | Returns 2 static frames: `main` at `currentLine`, `mockFunction` at line 42 |
| `scopes` | `handleScopes` | L478-511 | Returns Locals (x=10, y=20, result=30) and Globals scopes with new variable refs each call |
| `variables` | `handleVariables` | L513-537 | Looks up `variableHandles` by reference |
| `continue` | `handleContinue` | L554-613 | ACK; after 200ms finds next BP after currentLine or terminates |
| `next` | `handleNext` | L615-638 | Increments `currentLine`, sends `stopped/step` after 50ms |
| `stepIn` | `handleStepIn` | L640-662 | Same as next |
| `stepOut` | `handleStepOut` | L664-686 | Same as next |
| `pause` | `handlePause` | L688-707 | ACK + immediate `stopped/pause` event |
| `evaluate` | `handleEvaluate` | L539-552 | Returns `'mock_value'` |
| `disconnect` | `handleDisconnect` | L709-724 | ACK; exits after 100ms unless TCP server mode |
| `terminate` | `handleTerminate` | L726-747 | ACK + `terminated` event; exits after 100ms unless TCP server mode |

**Notable simulation behaviors:**
- `handleLaunch` (L358-396): Automatically hits the lowest-line-number breakpoint 200ms after launch, or sends `terminated`+`exited` if no breakpoints set.
- `handleContinue` (L567-612): Finds next breakpoint *after* `currentLine` (not at or equal), or terminates if none. Uses 200ms timeout.
- `handleScopes` creates new variable reference IDs on every call (L482-500) — references accumulate in `variableHandles` with no cleanup.

**Helpers:**
- `sendResponse` (L749-753): Guards on `this.connection` existence.
- `sendEvent` (L755-759): Guards on `this.connection` existence.
- `sendErrorResponse` (L761-777): Sends `success: false` with error body `{id, format}`.
- `getOrCreateVariableReference` (L779-783): Always creates a NEW reference (despite "getOrCreate" naming — no lookup by content).
- `log` (L185-188): Writes to `stderr` to avoid polluting DAP stream.

---

### CLI Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port <n>` | stdio | TCP port to listen on |
| `--host <h>` | `localhost` | TCP bind host |
| `--session <s>` | `mock-session` | Session identifier (logging only) |

---

### Dependencies

- `@vscode/debugprotocol` — DAP type definitions only (no runtime behavior)
- `path` — CWD-relative stack frame paths (L448, L456)
- `net` — TCP server for `--port` mode
- `stream` — `Readable`/`Writable` types for `DAPConnection`
