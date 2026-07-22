# tests\unit\proxy\minimal-dap.test.ts
@source-hash: b937b945c0ccaa36
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:43Z

## Unit Tests: MinimalDapClient

Comprehensive unit test suite for `MinimalDapClient` (from `src/proxy/minimal-dap.js`), covering TCP connection lifecycle, DAP protocol message parsing, request/response correlation, child session management, reverse request handling, and configuration deferral logic.

### Test Infrastructure

**Mocks (L11-36):**
- `net` module fully mocked via `vi.mock('net')` (L12) — `net.createConnection` returns a controlled `mockSocket` (EventEmitter + write/end/destroy)
- Logger mocked via `vi.mock('../../../src/utils/logger.js')` with hoisted `loggerInstances` array (L22) to capture all logger instances for assertion
- `loggerInstances` tracks every `createLogger()` call; tests use `loggerInstances.at(-1)` to reference the most recent logger

**Shared Fixtures (L38-117):**
- `mockSocket` (L40): EventEmitter augmented with `write`, `end`, `destroy`, `destroyed` — created fresh in `beforeEach`
- `ChildSessionManagerStub` type (L42-49): typed stub combining `ChildSessionManager + EventEmitter` with vi.fn mocks for all manager methods
- `createChildSessionManagerStub()` (L51-60): factory returning EventEmitter with mocked CSM methods
- `createMockSocket()` (L63-75): socket factory with write callback support
- `createDapMessage(content)` (L78-82): encodes any object as a valid DAP wire message (`Content-Length: N\r\n\r\n{json}`)
- `splitBuffer(buffer, chunkSizes)` (L85-96): splits a Buffer into partial chunks for streaming tests
- `echoSocket(capturedRequests?)` (L1470-1493): helper socket that auto-responds to every outgoing request with a success response (captures requests optionally), uses `client` from outer scope via closure

**Setup/Teardown:**
- `beforeEach` (L98-109): clears mocks, creates fresh `mockSocket`, stubs `net.createConnection` to call callback via `setImmediate`, creates `new MinimalDapClient('localhost', 5678)`
- `afterEach` (L111-117): calls `client.shutdown()`, restores all mocks

### Test Groups

**Connection Management (L119-191):** TCP connect success, connection error rejection (error should NOT emit to EventEmitter during connect phase — prevents uncaught exceptions), socket close → `close` event, post-connect socket error → `error` event + logger, close → `cleanup()` call

**Message Parsing (L193-340):** Complete message, partial chunks across events, multiple messages in one event, malformed/non-`Content-Length` headers (skipped gracefully), invalid JSON (logged as error), non-numeric Content-Length warns and discards (L285-323, accesses `rawData` internal), zero/negative Content-Length warns and discards, incomplete body buffering

**Request/Response Handling (L342-541):**
- Wire format: `Content-Length: N\r\n\r\n{seq, type, command, arguments}` (L343-369)
- Response correlation by `request_seq` (L371-391)
- Failed responses reject with `message` field (L393-410)
- Concurrent out-of-order responses (L412-456)
- 30-second timeout via injected `fakeTimers` that fires 30000ms immediately (L458-490); message arriving after timeout is silently discarded
- Per-request `timeoutMs` override (L492-518, issue #142)
- Unknown `request_seq` silently ignored (L520-533)
- Destroyed socket rejects immediately with `'Socket not connected or destroyed'` (L535-540)

**Payload Sanitization (L543-605, issue #146):**
- `env` objects in `launch` args redacted from logger but sent verbatim on wire (L550-565)
- Reverse request `env` args redacted from logger (L568-580)
- `DAP_TRACE_FILE` trace file also gets sanitized env (L582-604); uses real `fs.readFileSync`

**Event Handling (L607-668):** Events emit both `event.event`-named event (body only) and generic `event` event (full message). Tests `output`, `stopped`, `thread` events.

**Disconnection (L670-725):** Graceful disconnect calls `socket.end()` + `socket.destroy()`, pending requests rejected with `'DAP client disconnected'`, idempotent double-disconnect (only calls end/destroy once), listeners removed after disconnect, no-op when socket already destroyed

**Socket Backpressure (L727-751):** `write` returning `false` still allows request to complete — backpressure not implemented

**Large Message Handling (L753-788):** 10K-char body split into 100-byte chunks correctly reassembled

**Edge Cases (L790-828):** Empty data buffer, response missing `command`, unknown message type (logs warn, no crash)

**Shutdown Behaviour (L831-899):**
- Write callback error clears `pendingRequests` and rejects (L832-843)
- `writeMessage` on destroyed socket logs error (L845-865, tests internal `writeMessage` directly)
- Child `shutdown()` throwing is caught and warned, `childSessions` cleared, `activeChild` nulled (L867-888)
- Duplicate shutdown logs debug (L890-898)

**Configuration Deferral (L901-960):** `deferParentConfigDoneActive=true` holds `configurationDone` until 1500ms timeout (injected fake timers fire at 0ms), then flushes and sends; `parentConfigDoneDeferred` set to null after flush; `suppressNextConfigDoneDeferral` reset to false

**Child Session Integration (L962-1219):**
- `childCreated` event populates `childSessions` and `activeChild` (L963-994)
- `childEvent` event forwarded to parent client listeners (L981-989)
- `childClosed` event clears sessions and `activeChild` (L991-993)
- `DAP_TRACE_FILE` → `fs.appendFileSync` called (L996-1030)
- `startDebugging` reverse request delegates to `createChildSession` with `pendingId` (L1032-1059)
- `setBreakpoints` mirrors to `storeBreakpoints` on CSM (L1061-1105)
- Child-scoped commands routed to `activeChild.sendRequest` with 30s timeout (L1107-1143)
- Child poll loop: waits for `getActiveChild` to return non-null when `isAdoptionInProgress` (L1145-1188)
- Synthetic error response when child never becomes ready within `childInitTimeout` (L1190-1218)

**Reverse Request Handling (L1221-1413):**
- No policy handler → `sendResponse(request, {})` (L1222-1238)
- `handleReverseRequest: undefined` → default ack (L1240-1256)
- Policy `handled: true` → no `createChildSession`, no `sendResponse` (L1258-1286)
- `createChildSession: true` + `deferParentConfigDone: true` sets `deferParentConfigDoneActive` (L1288-1326)
- Policy throws → falls back to default `sendResponse(request, {})` (L1328-1351)
- Policy returns `handled: false` → default ack (L1353-1377)
- `createChildSession` rejection logged without throwing (L1379-1413)

**Request Error Handling (L1416-1464):** Write failure rejects + clears pending, missing socket rejects, `writeMessage` without socket logs error

**Adapter ID Normalization (L1495-1550):** `normalizeAdapterId` policy hook mutates `adapterID` in `initialize` args on wire; normalizer throw passes original; no-op when `adapterID` absent; identity normalizer leaves args unchanged

**Non-stackTrace Child Wait Loop (L1552-1601):** Polls `getActiveChild` when `hasActiveChildren=true` and routes to child; parent socket NOT written to

**Child Fallback Behavior (L1603-1719):**
- `'DAP client disconnected'` error on graceful-completion command → synthetic success response (L1604-1636)
- `'Socket not connected'` on non-graceful command → falls through to parent socket (L1638-1687)
- Unrelated child error re-thrown (L1689-1718)

**Configuration Deferral Edge Cases (L1721-1775):**
- Second `configurationDone` during active deferral replaces first (clears old timer, sets new) (L1722-1760)
- `suppressNextConfigDoneDeferral=true` bypasses deferral and resets flag (L1762-1774)

**Trace File Error Handling (L1777-1817):** `appendFileSync` throwing `'disk full'` is swallowed; request still completes

**Child Config Enrichment (L1819-1863, issue #124):**
- Config unchanged when no `lastStartRequestArgs` recorded (L1830-1833)
- Config unchanged for `request: 'launch'` (L1836-1839)
- `request: 'attach'` threads `request` + `stopOnEntry` into `parentConfig` without mutating original (L1843-1853)
- `stopOnEntry` omitted when not boolean in attach args (L1855-1862)

### Key Patterns
- Internal private methods tested via `(client as unknown as {...}).method()` type casts — `handleData`, `handleProtocolMessage`, `writeMessage`, `enrichChildConfig`, `cleanup`, `sendResponse`, `sleep`, `dapBehavior`, `childSessions`, `activeChild`, `pendingRequests`, `rawData`, `socket`, `parentConfigDoneDeferred`, `deferParentConfigDoneActive`, `suppressNextConfigDoneDeferral`, `childSessionManager`, `lastStartRequestArgs`
- Injected `timers` option on `MinimalDapClient` constructor enables deterministic timeout testing
- `echoSocket` helper (L1470-1493) closes the request loop without manual `handleProtocolMessage` calls in most tests