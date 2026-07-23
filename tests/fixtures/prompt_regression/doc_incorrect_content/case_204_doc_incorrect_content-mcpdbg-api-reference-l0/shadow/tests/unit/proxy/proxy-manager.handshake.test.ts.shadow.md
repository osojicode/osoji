# tests\unit\proxy\proxy-manager.handshake.test.ts
@source-hash: 7dbfe591b71945e6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:51Z

## Unit Tests: ProxyManager `sendInitWithRetry` (Handshake Logic)

Tests the private `sendInitWithRetry` method on `ProxyManager`, which implements a retry-with-backoff handshake initialization protocol. All tests use fake timers to control async timing deterministically.

### Test Suite Structure

**Suite:** `ProxyManager sendInitWithRetry` (L8–119)

**Shared Stubs (L9–33):**
- `launcherStub` (L9–11): `IProxyProcessLauncher` with mocked `launchProxy`
- `fsStub` (L12–27): `IFileSystem` with all methods mocked (ensureDir, pathExists, readFile, writeFile, readdir, stat, unlink, rmdir, remove, copy, outputFile, existsSync, exists, ensureDirSync)
- `loggerStub` (L28–33): `ILogger` with mocked info/warn/error/debug

**Setup (L37–39):** `ProxyManager` is instantiated with `null` as first arg (no config/transport) and the three stubs.

**Teardown (L41–44):** Restores all mocks and real timers after each test.

---

### Test Cases

#### 1. `resolves when init acknowledgement arrives within the first window` (L46–62)
- Spies on private `sendCommand`, mocks it to emit `'init-received'` event (on the manager as EventEmitter) after 160ms
- Calls `sendInitWithRetry({ cmd: 'init' })`
- Advances timers 160ms → `init-received` fires → promise resolves
- **Asserts:** `sendCommand` called exactly **once** (no retry needed)
- **Implies:** ack timeout window is >160ms (≥500ms based on test 3)

#### 2. `retries when acknowledgement arrives after the first timeout` (L64–87)
- First attempt emits `init-received` after 600ms (after 500ms timeout fires); second attempt emits after 100ms
- Timer sequence: +600ms (first ack lost + timeout expires) → `await Promise.resolve()` → +500ms (backoff) → `await Promise.resolve()` → +100ms (second ack arrives)
- **Asserts:** `sendCommand` called exactly **twice**
- **Implies:** First ack timeout is ~500ms; backoff before retry is ~500ms

#### 3. `throws after exhausting retries when acknowledgement never arrives` (L89–118)
- `sendCommand` mock does nothing (never emits `init-received`)
- Sets `lastExitDetails` (L95–100): `{ code: 0, signal: null, timestamp: Date.now(), capturedStderr: ['timeout'] }` on manager to simulate prior process exit context
- Advances through ack timeout sequence: `[500, 1000, 2000, 4000, 8000, 8000]` (L106) — each advance fires ack timeout, then a matching backoff delay
- **Asserts:** Rejects with `'Failed to initialize proxy'` (L116); `sendCommand` called **6 times** (maximum retry count)
- **Implies:** Exponential backoff up to 8000ms cap, max 6 total attempts

---

### Key Behavioral Contracts Tested

| Behavior | Evidence |
|---|---|
| First ack timeout | ~500ms (test 2 step: `advanceTimersByTime(600)` crosses it) |
| Retry backoff delays | Exponential: 500, 1000, 2000, 4000, 8000, 8000ms (L106) |
| Max retry attempts | 6 (L117: `toHaveBeenCalledTimes(6)`) |
| Failure message | `'Failed to initialize proxy'` (L116) |
| Event used for ack | `'init-received'` emitted on manager (L51, L72) |
| Manager is EventEmitter | Cast via `manager as unknown as EventEmitter` (L51) |

### Access Patterns
- `sendInitWithRetry` is accessed as a private method via double type cast: `(manager as unknown as { sendInitWithRetry: ... })` (L54, L75, L102)
- `sendCommand` is accessed similarly as a private method (L49, L68, L92)
- `lastExitDetails` is written directly as a private field (L95)
