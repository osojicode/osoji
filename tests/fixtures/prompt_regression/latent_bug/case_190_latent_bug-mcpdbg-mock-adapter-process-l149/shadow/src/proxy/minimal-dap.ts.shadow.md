# src\proxy\minimal-dap.ts
@source-hash: 3e720eb65e6524ca
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:11Z

## MinimalDapClient (L35–774)

Lightweight DAP (Debug Adapter Protocol) client that communicates with debug adapters over TCP sockets. Implements the DAP wire format (HTTP-like `Content-Length` framing), handles reverse requests from adapters, routes commands to child sessions, and manages multi-session scenarios (e.g., js-debug's `startDebugging` reverse request).

---

### Key Classes & Fields

**`MinimalDapClient extends EventEmitter` (L35–774)**  
Primary public class. Manages a single TCP socket to a debug adapter. Supports:
- Bidirectional DAP message framing/parsing (`handleData`, L132–190)
- Pending request tracking with per-request timeouts (`pendingRequests`, L39–43)
- Policy-driven DAP behavior (`AdapterPolicy`, `DapClientBehavior`) injected via constructor (L81)
- Child session lifecycle via `ChildSessionManager` (L92–125)
- `configurationDone` deferral mechanism (L450–479) to avoid premature process resume
- Optional trace-file logging of all inbound/outbound messages (`traceFile`, L48, `appendTrace`, L330–343)

**Constructor (L81–126):**
- `host`, `port`: TCP endpoint for the debug adapter
- `policy`: `AdapterPolicy` (defaults to `DefaultAdapterPolicy`) — controls child session support, routing, and behavior normalization
- `options`: `MinimalDapClientOptions` — injectable `childSessionManagerFactory` and timer implementations (for testing)
- Conditionally creates a `ChildSessionManager` when `policy.supportsReverseStartDebugging` is true; wires up `childCreated`, `childEvent`, `childError`, `childClosed` events

---

### Key Private State

| Field | Type | Purpose |
|---|---|---|
| `socket` | `Socket \| null` | Active TCP connection |
| `rawData` | `Buffer` | Accumulator for incomplete incoming bytes |
| `contentLength` | `number` | Bytes expected for current message body (-1 = parsing header) |
| `pendingRequests` | `Map<number, {resolve,reject,timer}>` | In-flight request promises keyed by `seq` |
| `nextSeq` | `number` | Monotonically increasing sequence counter |
| `isDisconnectingOrDisconnected` | `boolean` | Guards against double-shutdown and post-close errors |
| `lastStartRequestArgs` | `Record<string,unknown> \| null` | Last `launch`/`attach` args; threaded into child configs (issue #124) |
| `deferParentConfigDoneActive` | `boolean` | When true, next `configurationDone` is deferred |
| `parentConfigDoneDeferred` | object \| null | Saved promise callbacks for deferred `configurationDone` |
| `suppressNextConfigDoneDeferral` | `boolean` | Single-pass suppression of `configurationDone` deferral |
| `childSessions` | `Map<string, MinimalDapClient>` | Active child clients by pendingId |
| `activeChild` | `MinimalDapClient \| null` | Currently routed child session |
| `adoptedTargets` | `Set<string>` | Targets that have been adopted |

---

### Key Methods

**`connect(): Promise<void>` (L351–399)**  
Creates TCP socket via `net.createConnection`. Wires `data`, `error`, `close` handlers. Rejects promise on connection failure or premature close.

**`sendRequest<T>(command, args?, timeoutMs?): Promise<T>` (L424–688)**  
Core request dispatch. Pipeline:
1. Guards: socket live, not disconnecting
2. Records `lastStartRequestArgs` for `launch`/`attach` (L441–446)
3. Optionally defers `configurationDone` for 1500ms (L450–479)
4. Routes to child session if `childSessionManager.shouldRouteToChild(command)` (L483–596)
   - Special `stackTrace` polling loop: waits up to `dapBehavior.childInitTimeout ?? 12000`ms (L508–523)
   - Fallback logic: returns synthetic success responses for `continue`/`disconnect`/`terminate` on child unavailability (L559–579)
5. Mirrors `setBreakpoints` to `ChildSessionManager` (L599–613)
6. Normalizes `initialize.adapterID` via `dapBehavior.normalizeAdapterId` (L619–633)
7. Encodes and writes request with `Content-Length` framing; registers timeout timer (L650–687)

**`handleData(data: Buffer): void` (L132–190)**  
Streaming parser: accumulates bytes in `rawData`, extracts `Content-Length` header, slices complete message bodies, delegates to `handleProtocolMessage`.

**`handleProtocolMessage(message): Promise<void>` (L192–328)**  
Dispatches by `message.type`:
- `response`: resolves/rejects matching pending request (L230–249)
- `event`: emits `event.event` and generic `'event'` (L250–257)  
- `request` (reverse): tries `dapBehavior.handleReverseRequest` first; falls back to default `runInTerminal` / catch-all empty-body ACK (L258–327)

**`shutdown(reason?): void` (L718–750)**  
Idempotent shutdown: sets flag, shuts down child sessions, calls `cleanup(true)`, destroys socket.

**`disconnect(): void` (L714–716)**  
Public alias for `shutdown('Client disconnect requested')`.

**`cleanup(immediate?): void` (L752–773)**  
Rejects all pending requests with `'DAP client disconnected'`, clears buffer, removes all listeners (immediately or via `setTimeout(0)`).

**`enrichChildConfig(config): ChildSessionConfig` (L409–422)**  
Private helper: merges parent `attach`/`stopOnEntry` intent from `lastStartRequestArgs` into child session config. No-op for launch-mode. Addresses issue #124.

**`sendResponse(request, body, success, errorMessage): void` (L702–712)**  
Encodes and writes a DAP response to an incoming reverse request.

**`writeMessage(message): void` (L690–700)**  
Low-level `Content-Length`-framed write to socket.

**`appendTrace(direction, payload): void` (L330–343)**  
Appends sanitized JSON lines to `DAP_TRACE_FILE` when set. Env vars redacted via `sanitizePayloadForLogging`.

**`sleep(ms): Promise<void>` (L345–349)**  
Injectable timer-based delay used in child wait loops.

---

### Type: `MinimalDapClientOptions` (L25–31)
Injectable factories/mocks:
- `childSessionManagerFactory`: overrides `ChildSessionManager` construction (for testing)
- `timers`: overrides `setTimeout`/`clearTimeout` (for testing)

---

### Event Emissions
- `event.event` (specific, e.g. `'stopped'`, `'initialized'`) — forwarded from adapter events and child sessions
- `'event'` — generic catch-all with full `DebugProtocol.Event` object
- `'error'` — socket errors (only after successful connect)
- `'close'` — socket close

---

### DAP Wire Format
Uses `Content-Length: N\r\n\r\n{json}` framing (constant `TWO_CRLF`, L33). Same algorithm as VSCode's `ProtocolServer`.

---

### Dependencies
- `net` (Node stdlib): TCP socket
- `EventEmitter` (Node stdlib): event forwarding
- `@vscode/debugprotocol`: DAP type definitions
- `@debugmcp/shared`: `AdapterPolicy`, `DefaultAdapterPolicy`, `DapClientBehavior`, `DapClientContext`, `ChildSessionConfig`, `sanitizePayloadForLogging`
- `./child-session-manager`: `ChildSessionManager`, `ChildSessionOptions`
- `../utils/logger`: `createLogger`
- `../errors/debug-errors`: `getErrorMessage`
- `fs`, `path` (Node stdlib): trace file append and path resolution

---

### Critical Invariants / Constraints
- `isDisconnectingOrDisconnected` must be set before any socket teardown to prevent error-event crashes after listener removal
- `pendingRequests` map is always cleared (with rejections) on cleanup — no dangling promises
- `configurationDone` deferral is single-use per cycle, controlled by `suppressNextConfigDoneDeferral`
- `lastStartRequestArgs` only stores `launch`/`attach` commands; used exclusively in `enrichChildConfig`
- Child session routing only activates when `policy.supportsReverseStartDebugging` is true and a `ChildSessionManager` was created
- `stackTrace` has special wait logic separate from other routed commands