# packages\adapter-mock\src\mock-adapter-process.ts
@source-hash: b65967e4dccf0f9a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:27Z

## Mock Debug Adapter Process

Entry point script (`#!/usr/bin/env node`) that implements a complete DAP (Debug Adapter Protocol) server for testing purposes. Spawned as a child process by the mock adapter package. Supports both stdio and TCP communication modes.

---

### Architecture Overview

Two cooperating classes:
1. **`DAPConnection` (L16–88)** — Low-level DAP framing (HTTP-style `Content-Length` headers over a byte stream). Handles message parsing and serialization.
2. **`MockDebugAdapterProcess` (L97–784)** — High-level mock DAP server. Handles all standard DAP request commands with simulated responses and events.

Instantiation at module level (L787): `new MockDebugAdapterProcess()` — starts automatically on process launch.

---

### `DAPConnection` (L16–88)

Reads raw bytes from a `Readable` (default: `process.stdin`), parses DAP framing, dispatches `DebugProtocol.Request` objects to a registered handler.

- **`constructor(input, output)`** (L19–22): Defaults to `process.stdin`/`process.stdout`.
- **`start()`** (L24–29): Attaches `data` listener; feeds chunks into `messageBuffer`.
- **`on(event, handler)`** (L31–38): Registers `'request'` or `'disconnect'` handlers. `'disconnect'` maps to stream `end`/`close` events.
- **`sendResponse(response)`** (L40–42) / **`sendEvent(event)`** (L44–46): Both delegate to `sendMessage`.
- **`processMessages()`** (L50–81): Parses DAP framing: finds `\r\n\r\n` header separator, extracts `Content-Length`, does byte-aware buffer slicing (L66–70) to handle multi-byte UTF-8 characters correctly. Dispatches to `onRequest` if `message.type === 'request'`.
- **`sendMessage(message)`** (L83–87): Serializes to JSON, computes byte length, writes `Content-Length: N\r\n\r\n<json>`.

---

### `createConnection(input?, output?)` (L90–92)

Factory function for `DAPConnection`. Internal helper, not exported.

---

### `MockDebugAdapterProcess` (L97–784)

**State:**
- `breakpoints: Map<string, DebugProtocol.Breakpoint[]>` — keyed by file path (L100)
- `variableHandles: Map<number, { variables: [...] }>` — ref → variable data (L101)
- `nextVariableReference: number` — starts at 1000, increments per scope (L102)
- `currentLine: number` — simulated execution position, starts at 1 (L103)
- `threads: [{ id: 1, name: 'main' }]` — single hardcoded thread (L104)

**CLI Arguments parsed in constructor (L108–128):**
- `--port <n>`: TCP mode
- `--host <str>`: TCP host (default: `'localhost'`)
- `--session <str>`: Session ID for logging (default: `'mock-session'`)

**Communication setup (L133–141):**
- With `--port`: calls `setupTCPServer(host, port)` — creates a `net.Server`, allows reconnections (doesn't exit on client disconnect).
- Without `--port`: stdio mode — `createConnection()` → `setupConnection()` → `start()`.

**`setupTCPServer(host, port)`** (L144–171): Creates TCP server. Each accepted socket gets its own `DAPConnection`. Server errors cause `process.exit(1)`.

**`setupConnection(connection)`** (L173–183): Registers `handleRequest` and a disconnect handler. In stdio mode, disconnect causes `process.exit(0)`.

**Request dispatch — `handleRequest(request)`** (L190–261): Switch on `request.command`. Supported commands:
- `initialize`, `configurationDone`, `launch`, `setBreakpoints`, `threads`, `stackTrace`, `scopes`, `variables`, `continue`, `next`, `stepIn`, `stepOut`, `pause`, `evaluate`, `disconnect`, `terminate`
- Unknown commands → `sendErrorResponse` with id `1000`.

**Key handler behaviors:**

- **`handleInitialize`** (L263–316): Returns full capabilities object (many `false`), then fires `initialized` event immediately.
- **`handleLaunch`** (L328–397): If `stopOnEntry`, fires `stopped/entry` after 100ms. Otherwise simulates running to first breakpoint (200ms delay); if no breakpoints, fires `terminated` + `exited`.
- **`handleSetBreakpoints`** (L399–426): Verifies all breakpoints immediately (`verified: true`). Stores by `args.source?.path || 'unknown'`.
- **`handleStackTrace`** (L441–476): Returns hardcoded 2-frame stack: `main` at `currentLine` in `main.mock`, and `mockFunction` at line 42 in `lib.mock`.
- **`handleScopes`** (L478–511): Returns 2 scopes (`Locals` with x=10, y=20, result=30; `Globals` with `__name__` and `__file__`). Each creates a new variable reference handle.
- **`handleVariables`** (L513–537): Looks up `variablesReference` in `variableHandles` map.
- **`handleContinue`** (L554–613): Finds next breakpoint after `currentLine` (200ms delay). Stops at it or fires `terminated`+`exited`.
- **`handleNext/StepIn/StepOut`** (L615–686): All increment `currentLine` by 1, send `stopped/step` after 50ms.
- **`handlePause`** (L688–707): Immediately fires `stopped/pause`.
- **`handleDisconnect`** (L709–723) / **`handleTerminate`** (L726–747): In TCP server mode, returns without exiting. In stdio mode, calls `process.exit(0)` after 100ms. `terminate` additionally fires `terminated` event.

**`getOrCreateVariableReference(data)`** (L779–783): Always creates a NEW handle (does not deduplicate). Each call to `handleScopes` creates fresh handles each time.

**Logging:** All log output goes to `stderr` via `console.error` (L187) to avoid corrupting the DAP framing on stdout.

---

### Important Constraints / Invariants

- `seq: 0` is used for all outgoing responses and events — sequence numbers are not tracked/incremented.
- In TCP mode, only one `connection` is active at a time (last connected client wins — `this.connection` is overwritten per-socket, L149).
- `variableHandles` grows unboundedly across sessions; handles from prior scopes calls accumulate.
- `handleEvaluate` accepts `DebugProtocol.Request` (not `EvaluateRequest`) — type is widened intentionally for simplicity (L539).
- Breakpoint IDs use `Math.random()` (L406) — not deterministic across runs.
