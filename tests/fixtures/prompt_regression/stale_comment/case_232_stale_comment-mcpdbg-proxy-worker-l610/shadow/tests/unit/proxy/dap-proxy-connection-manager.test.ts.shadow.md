# tests\unit\proxy\dap-proxy-connection-manager.test.ts
@source-hash: c2dba0600b095bb6
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:00Z

## Unit Tests: `DapConnectionManager`

Tests for `DapConnectionManager` from `src/proxy/dap-proxy-connection-manager.js`, covering connection retry logic, session initialization, event handler setup, disconnection lifecycle, DAP request sending, and concurrent operation handling.

### Test Structure

**Top-level suite:** `DapConnectionManager` (L10–819)

**Shared fixtures** (set up in `beforeEach`, L47–77):
- `mockDapClient` (L11–20, L51–63): Manual mock with vitest `MockInstance` for `connect`, `disconnect`, `shutdown`, `sendRequest`, `on`, `off`, `once`, `removeAllListeners`
- `mockDapClientFactory` (L22, L65–67): `IDapClientFactory` mock; `create` returns `mockDapClient`
- `mockLogger` (L23, L69–74): `ILogger` mock with `info`, `error`, `debug`, `warn`
- `connectionManager` (L24, L76): `DapConnectionManager` instance under test

**Cleanup** (L79–84): Clears timers, restores real timers, restores all mocks.

**Test helpers** (L27–45):
- `waitForRetries(count)` (L27–32): Advances fake timers by 200ms × `count` (matches `CONNECT_RETRY_INTERVAL`) plus a microtask yield per retry
- `expectDisconnectCleanup()` (L34–38): Asserts logger received `[ConnectionManager] Client disconnected` message
- `errorScenarios` (L40–45): Parameterized error table (`ECONNREFUSED`, `ETIMEDOUT`, `ENOTFOUND`, Unknown error)

---

### Describe Blocks & Key Test Cases

#### `connectWithRetry` (L86–240)
- **First attempt success** (L87–102): Advances 500ms (INITIAL_CONNECT_DELAY), verifies factory called with host/port, `on`/`off` error handler lifecycle, returns client
- **Retry on failure** (L104–123): 2 rejections then success → 3 total connect calls, 2 `warn` logs
- **Max retry exhaustion** (L125–147): 60 retries (CONNECT_RETRY_INTERVAL × 60) → rejects with `'Failed to connect DAP client: ECONNREFUSED'`, verifies error log and `off` cleanup
- **Temporary error event during connection** (L149–175): Captures `on('error')` handler, emits it, verifies `debug` log with expected message (not a fatal error)
- **Parameterized error types** (L177–193): `it.each(errorScenarios)` — each retries once and succeeds, verifies `warn` log format
- **Intermediate retry count** (L195–218): Fails 9 times, verifies state at mid-point (6 calls after 5 retries) and final (10 calls)
- **Cleanup on synchronous exception** (L220–239): `connect` throws (not rejects) → verifies `off` cleanup still occurs after exhaustion

#### `initializeSession` (L242–269)
- **Correct request shape** (L243–259): Verifies exact `sendRequest('initialize', {...})` call with `clientID: 'mcp-proxy-<sessionId>'`, `clientName: 'MCP Debug Proxy'`, `adapterID: 'python'`, locale/format flags
- **Failure propagation** (L261–268): Rejected `sendRequest` re-throws

#### `setupEventHandlers` (L271–317)
- **All handlers** (L272–296): Verifies `on` called for all 9 events: `initialized`, `output`, `stopped`, `continued`, `thread`, `exited`, `terminated`, `error`, `close`
- **Partial handlers** (L298–309): Only 2 handlers → exactly 2 `on` calls
- **Empty handlers** (L311–316): No `on` calls, logs `[ConnectionManager] DAP event handlers set up`

#### `disconnect` (L319–429)
- **Null client** (L320–327): Early return with specific info log, no `sendRequest`
- **Default terminateDebuggee=true** (L329–339): `sendRequest('disconnect', { terminateDebuggee: true })` + `client.disconnect()`
- **terminateDebuggee=false** (L341–349): Explicit false passed through
- **Timeout handling** (L351–366): `sendRequest` takes 2000ms, timeout fires at ~1100ms → warn log with `'DAP disconnect request timed out after 1000ms'`, still calls `client.disconnect()`
- **Request error** (L368–378): Rejected `sendRequest` → warn log, still calls `client.disconnect()`
- **client.disconnect() throws** (L380–392): `sendRequest` succeeds but `disconnect()` throws → error log with `Error` object
- **Both errors** (L394–409): Both fail → both warn and error logs
- **Race: disconnect before timeout** (L411–428): Resolves at 500ms (timeout is 1000ms) → success info log, no timeout warn

#### `sendLaunchRequest` (L431–503)
- **Default args** (L434–447): Verifies `sendRequest('launch', { program, stopOnEntry: true, noDebug: false, args: [], console: 'internalConsole', justMyCode: true })`
- **Custom args** (L449–468): `stopOnEntry=false`, `args=['--arg1','value1']`, `justMyCode=false`
- **Failure propagation** (L470–477)
- **Env var redaction** (L479–502): Passes `env: { GITHUB_PAT: 'github_pat_LOGLEAK123' }` → adapter receives real value, but log output must not contain the token; log must contain `'env vars redacted'`

#### `sendAttachRequest` (L505–525)
- **Env var redaction** (L506–524): Same pattern — adapter receives `{ SECRET_TOKEN: 'attach-secret-1' }`, but value must not appear in logs

#### `setBreakpoints` (L527–756)
- **Single BP** (L530–554): Source name extracted from path (`source.py`), `condition: undefined` passed
- **Multiple BPs** (L556–594): 3 breakpoints, verifies array length
- **Conditional BPs** (L596–630): `condition` strings passed through
- **Empty array** (L632–656): Empty `breakpoints: []` sent
- **Invalid data** (L658–681): `verified: false`, negative line — passes through to adapter
- **Large array (100 BPs)** (L683–711): Verifies info log `Setting 100 breakpoint(s) for /path/to/source.py`
- **Duplicate lines** (L713–742): All 4 entries (including duplicates) sent unchanged
- **Failure propagation** (L744–755)

#### `sendConfigurationDone` (L758–778)
- **Success** (L759–768): `sendRequest('configurationDone', {})` + info log `'"configurationDone" sent.'`
- **Failure** (L770–777)

#### State Management / Concurrent Operations (L780–818)
- **Concurrent connects** (L781–796): Two simultaneous `connectWithRetry` calls to different ports → factory called twice with correct args, both resolve independently
- **Rapid disconnect/reconnect** (L798–817): Connect → disconnect → reconnect → `disconnect` called once, factory called twice

---

### Critical Constants (inferred from tests)
- `INITIAL_CONNECT_DELAY`: 500ms (L93, L113)
- `CONNECT_RETRY_INTERVAL`: 200ms (L29)
- `MAX_CONNECT_RETRIES`: 60 (L137, L142)
- DAP disconnect timeout: 1000ms (L363)

### Security Invariant Tested
Both `sendLaunchRequest` and `sendAttachRequest` must redact `env` values from logs while still forwarding the real environment to the DAP adapter (L479–524).