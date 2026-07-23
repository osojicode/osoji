# tests\unit\proxy\minimal-dap.test.ts
@source-hash: b937b945c0ccaa36
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:42Z

## Overview

Unit test suite for `MinimalDapClient` — the core DAP (Debug Adapter Protocol) TCP client in the proxy layer. Tests cover connection lifecycle, DAP message framing/parsing, request/response correlation, child session management, reverse request handling, configuration deferral, payload sanitization, and trace file output.

## File Structure

Single top-level `describe('MinimalDapClient', ...)` block (L38–L1865) containing:

### Test Infrastructure (L39–L117)

**`MockLoggerInstance` type** (L15–L20): Typed mock structure for logger instances with `info`, `error`, `debug`, `warn` vi.fn fields.

**`loggerInstances`** (L22): Hoisted array (`vi.hoisted`) collecting all logger mocks created during test runs; accessed via `loggerInstances.at(-1)` to get the most recently created logger.

**Logger mock** (L25–L36): Mocks `../../../src/utils/logger.js`'s `createLogger`, pushing each new logger into `loggerInstances`.

**`ChildSessionManagerStub` type** (L42–L49): Local type combining `ChildSessionManager`, `EventEmitter`, and vi.fn mocks for `createChildSession`, `getActiveChild`, `hasActiveChildren`, `shouldRouteToChild`, `storeBreakpoints`, `isAdoptionInProgress`.

**`createChildSessionManagerStub()`** (L51–L60): Factory returning an `EventEmitter` extended with all stub methods. Key defaults: `getActiveChild → null`, `hasActiveChildren → false`, `shouldRouteToChild → false`, `isAdoptionInProgress → false`.

**`createMockSocket()`** (L63–L75): Creates an `EventEmitter`-based socket mock with `write` (calls callback with null), `end`, `destroy`, `destroyed=false`.

**`createDapMessage(content)`** (L78–L82): Serializes any object to a proper DAP wire-format Buffer (`Content-Length: N\r\n\r\n{json}`).

**`splitBuffer(buffer, chunkSizes)`** (L85–L96): Utility to split a Buffer into specified chunk sizes for testing partial message delivery.

**`echoSocket(capturedRequests?)`** (L1470–L1493): Helper socket factory that auto-responds to every outgoing request with a synthetic success response via `setImmediate` + `handleProtocolMessage`. Captures parsed requests into optional array. Closes over outer `client` variable.

**`beforeEach`** (L98–L109): Clears mocks, creates fresh `mockSocket`, mocks `net.createConnection` to return `mockSocket` and call callback via `setImmediate`, creates `client = new MinimalDapClient('localhost', 5678)`.

**`afterEach`** (L111–L117): Calls `client.shutdown()` and `vi.restoreAllMocks()`.

## Test Groups

### Connection Management (L119–L191)
- Connect success: verifies `net.createConnection` called with `{host, port}` (L120–L128)
- Connection error: verifies `connect()` rejects but does NOT emit 'error' event during connection phase (L130–L154)
- Socket close → 'close' event emission (L156–L164)
- Post-connection socket error → emits 'error' event + logs `[MinimalDapClient] Socket error:` (L166–L178)
- Socket close calls `cleanup()` and logs `[MinimalDapClient] Socket closed` (L180–L190)

### Message Parsing (L193–L340)
- Complete DAP message parsing (L194–L211)
- Partial messages across multiple data events via `splitBuffer` (L213–L234)
- Multiple messages in one data event via concatenated buffers (L236–L262)
- Malformed headers (non-`Content-Length`) skipped gracefully (L264–L272)
- Invalid JSON → logs `[MinimalDapClient] Error parsing message:` (L274–L283)
- Non-numeric Content-Length → warns `[MinimalDapClient] Invalid Content-Length header encountered; discarding payload`, `rawData` cleared, `handleProtocolMessage` not called (L285–L300)
- Zero/negative Content-Length → same warning, called twice (L302–L323)
- Incomplete body buffered until rest arrives (L325–L339)

### Request/Response Handling (L342–L541)
- Request format: `Content-Length: N\r\n\r\n{seq,type,command,arguments}` (L343–L369)
- Response correlation by `request_seq` (L371–L391)
- Failed response (success=false) → rejects with `message` field (L393–L410)
- Concurrent out-of-order responses correctly correlated (L412–L456)
- 30s timeout: uses injected `timers` with fake `setTimeout` that fires 30000ms delay immediately; rejects with `"DAP request 'evaluate' (seq 1) timed out"` (L458–L490)
- Per-request `timeoutMs` override (60000ms): same pattern, verifies scheduled delay is 60000 (L492–L518)
- Unknown `request_seq` in response: no throw, just warn (L520–L533)
- Socket destroyed → rejects with `'Socket not connected or destroyed'` (L535–L541)

### Payload Sanitization (L543–L605)
- Outgoing `launch` with `env` object: secret NOT in any logger output, IS on wire; logs contain `'env vars redacted'` (L550–L566)
- Incoming reverse request with `env`: secret NOT logged (L568–L580)
- DAP trace file (`DAP_TRACE_FILE` env var): secret NOT in trace, `'env vars redacted'` IS in trace; uses real `fs.readFileSync` (L582–L604)

### Event Handling (L607–L668)
- DAP event emits both specific event name (e.g., `'output'` with body) and generic `'event'` with full message (L608–L630)
- Multiple event types (`stopped`, `thread`) (L632–L667)

### Disconnection (L670–L725)
- Graceful disconnect: calls `socket.end()` and `socket.destroy()` (L671–L678)
- Pending requests rejected with `'DAP client disconnected'` on disconnect (L680–L690)
- Idempotent disconnect: `end`/`destroy` called exactly once (L692–L700)
- Listener removal on disconnect (L702–L714)
- Disconnect when socket already destroyed: `end` not called (L716–L724)

### Socket Backpressure (L727–L751)
- `write` returning false still processes response correctly (L728–L750)

### Large Message Handling (L753–L788)
- 10KB body split into 100-byte chunks processed correctly (L754–L787)

### Edge Cases (L790–L828)
- Empty data event: no crash (L791–L797)
- Response missing `command` field: handled gracefully (L799–L813)
- Unknown message type: logs warning, no crash (L815–L827)

### Shutdown Behaviour (L831–L899)
- Write callback error → rejects `sendRequest`, `pendingRequests` map cleared (L832–L843)
- `writeMessage` on destroyed socket logs `[MinimalDapClient] Cannot write message, socket not connected/destroyed` (L845–L865)
- Child shutdown throwing → logs `[MinimalDapClient] Error shutting down child sessions:` with error message, clears `childSessions` and `activeChild` (L867–L888)
- Duplicate `shutdown()` → logs `[MinimalDapClient] Already disconnecting or disconnected'` (L890–L898)

### Configuration Deferral (L901–L960)
- `deferParentConfigDoneActive=true`: `configurationDone` is deferred (held) until 1500ms timeout fires immediately via fake timers, then sent and resolved (L902–L959)

### Child Session Integration (L962–L1219)
- `ChildSessionManager` events: `childCreated` → `childSessions` map + `activeChild` set; `childEvent` → re-emits as specific + generic 'event'; `childClosed` → clears map and `activeChild` (L963–L994)
- `DAP_TRACE_FILE`: `fs.appendFileSync` called on each request/response (L996–L1030)
- `startDebugging` with `__pendingTargetId` → delegates to `ChildSessionManager.createChildSession` with `{pendingId}` (L1032–L1059)
- `setBreakpoints` → calls `ChildSessionManager.storeBreakpoints` with path and breakpoints (L1061–L1105)
- Child-scoped routing: `shouldRouteToChild=true` → dispatches to `activeChild.sendRequest` with same args + default 30000ms timeout (L1107–L1143)
- Wait loop for child session: polls `getActiveChild` + `isAdoptionInProgress`, sleeps, eventually routes to child (L1145–L1188)
- `stackTrace` times out waiting for child → returns synthetic `{success:false, message:'Child session not ready...'}` (L1190–L1218)

### Reverse Request Handling (L1221–L1413)
- No policy handler: `runInTerminal` acknowledged with `sendResponse(request, {})` (L1222–L1238)
- `handleReverseRequest: undefined`: unknown command acknowledged (L1240–L1256)
- Policy returns `{handled: true}`: `sendResponse` NOT called (L1258–L1286)
- Policy returns `{handled: true, createChildSession: true, childConfig}` + `deferParentConfigDone=true`: `createChildSession` called, `deferParentConfigDoneActive=true`, `activeChild` set (L1288–L1326)
- Policy throws: falls back to `sendResponse(request, {})` (L1328–L1351)
- Policy returns `{handled: false}`: default ack sent (L1353–L1377)
- `createChildSession` rejects: error logged, no throw, `deferParentConfigDoneActive=false` (L1379–L1413)

### Request Error Handling (L1416–L1465)
- Write callback error: `sendRequest` rejects, `pendingRequests` cleared (L1417–L1434)
- Missing socket: `sendRequest` rejects with `'Socket not connected or destroyed'` (L1436–L1443)
- `writeMessage` on destroyed socket: error logged (L1445–L1464)

### Adapter ID Normalization (L1495–L1550)
- `normalizeAdapterId` mutates `adapterID` in the sent request (L1496–L1508)
- Normalizer throwing: original args sent (L1510–L1525)
- No `adapterID` in args: normalizer not invoked (L1527–L1537)
- Normalizer returning same value: args unchanged (L1539–L1549)

### Non-stackTrace Child Wait Loop (L1552–L1601)
- `hasActiveChildren=true`, `shouldRouteToChild=true`, `getActiveChild` returns null for first 3 polls then child: polls + sleeps, then routes to child (L1553–L1600)

### Child Fallback Behavior (L1603–L1719)
- Graceful-completion command (`continue`) + child disconnects with `'DAP client disconnected'` → synthetic `{success:true}` returned (L1604–L1637)
- Non-graceful command (`next`) + child disconnects with `'Socket not connected'` → falls through to parent socket (L1638–L1687)
- Unrelated child error → rethrows (L1689–L1718)

### Configuration Deferral Edge Cases (L1721–L1775)
- Second `configurationDone` while first is in-flight: first timer cleared, new deferred created (L1722–L1760)
- `suppressNextConfigDoneDeferral=true`: `configurationDone` bypasses deferral, flag reset to false (L1762–L1774)

### Trace File Error Handling (L1777–L1817)
- `fs.appendFileSync` throwing (`'disk full'`): error swallowed, `sendRequest` still resolves (L1778–L1816)

### Child Config Enrichment (L1819–L1863)
- No start request recorded → config unchanged (L1830–L1833)
- Launch-mode parent → config unchanged (L1836–L1841)
- Attach-mode parent → `request` and `stopOnEntry` threaded into `parentConfig`, original not mutated (L1843–L1852)
- Attach without boolean `stopOnEntry` → `stopOnEntry` omitted from enriched config (L1855–L1862)

## Key Internal APIs Accessed via Type Assertions

Tests directly access private members via `(client as any)` and `(client as unknown as {...})`:
- `rawData: Buffer` — internal parse buffer
- `pendingRequests: Map<number, unknown>` — in-flight request map
- `childSessions: Map<string, MinimalDapClient>` — tracked child sessions
- `activeChild: MinimalDapClient | null` — current active child
- `deferParentConfigDoneActive: boolean` — config deferral state
- `parentConfigDoneDeferred: {timer, reject} | null` — deferred config done holder
- `suppressNextConfigDoneDeferral: boolean` — bypass flag
- `socket: net.Socket | null` — underlying TCP socket
- `dapBehavior: DapClientBehavior` — policy behavior
- `childSessionManager: ChildSessionManager` — child session manager
- `lastStartRequestArgs` — recorded start arguments for enrichment
- `sleep: () => Promise<void>` — injectable sleep for wait loops
- `handleData(data: Buffer): void` — data handler
- `handleProtocolMessage(msg): void` — message dispatch
- `writeMessage(msg): void` — low-level write
- `sendResponse(req, body): void` — response sender
- `enrichChildConfig(config): config` — child config enrichment
- `cleanup()` — cleanup private method

## Dependencies

- **`MinimalDapClient`** from `../../../src/proxy/minimal-dap.js` — class under test
- **`ChildSessionManager`** from `../../../src/proxy/child-session-manager.js` — type import only, stubbed
- **`JsDebugAdapterPolicy`** from `@debugmcp/shared` — real policy used in child session tests
- **`DapClientBehavior`, `ReverseRequestResult`** from `@debugmcp/shared` — type imports for behavior stubs
- **`DebugProtocol`** from `@vscode/debugprotocol` — DAP message types
- **`net`** — fully mocked via `vi.mock('net')`
- **`fs`** — partially spied (`appendFileSync`, `readFileSync`, `rmSync`)
- **`events`** (EventEmitter) — used for mock socket and child session manager stubs

## Notable Patterns

1. **Hoisted logger tracking**: `vi.hoisted()` ensures `loggerInstances` array is available before mocks execute; `loggerInstances.at(-1)` retrieves the most recently instantiated logger per test.
2. **Fake timer injection**: Tests that need timeout behavior create new `MinimalDapClient` instances with `{timers: {setTimeout, clearTimeout}}` that fire specific delays immediately.
3. **Direct socket injection**: Tests bypass `net.createConnection` by directly assigning to `(client as any).socket`.
4. **echoSocket helper**: Shared socket factory that auto-responds to outgoing requests synchronously in `setImmediate`, enabling clean `await sendRequest(...)` patterns.
5. **DAP_TRACE_FILE env var**: Some tests set/delete `process.env.DAP_TRACE_FILE` directly; one uses `vi.stubEnv`.
