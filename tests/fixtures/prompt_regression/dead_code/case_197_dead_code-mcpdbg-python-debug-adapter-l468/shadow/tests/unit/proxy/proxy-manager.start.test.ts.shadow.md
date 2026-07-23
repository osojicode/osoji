# tests\unit\proxy\proxy-manager.start.test.ts
@source-hash: 3685702b3652390a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:53Z

## Purpose
Unit test suite for `ProxyManager.start` and related lifecycle methods. Tests cover the full initialization flow, retry logic, stderr capture/redaction, dry-run completion, DAP request handling, stop/cleanup, and proxy script resolution.

## Test Structure

### Top-level describe: `ProxyManager.start` (L25–1346)
Main test suite. Shared setup in `beforeEach` (L33–89) creates a `FakeProxyProcess`, mocks the process launcher, filesystem, and logger, and constructs a `ProxyManager(null, ...)` (no debug adapter).

### Nested describe: `ProxyManager helpers` (L1348–1493)
Secondary suite testing `findProxyScript` resolution paths and `prepareSpawnContext` with a `runtimeEnv` override.

## Key Fixtures

### `FakeProxyProcess` (L10–23)
Extends `EventEmitter`, implements `IProxyProcess`. Fields: `pid=4242`, `killed=false`, `exitCode`, `signalCode`, `stdin`, `stdout`, `stderr` (EventEmitter). Methods: `send` (vi.fn), `sendCommand` (vi.fn), `kill` (vi.fn), `waitForInitialization` (vi.fn resolves).

### `baseConfig` (L91–100)
`ProxyConfig` with `sessionId='session-123'`, `language=JAVASCRIPT`, `executablePath='node'`, `adapterHost='127.0.0.1'`, `adapterPort=9229`, `logDir='./.tmp/logs'`, `scriptPath='./tests/fixtures/app.js'`, `dryRunSpawn=true`.

### `completeStart` helper (L102–106)
Calls `proxyManager.start(config)` and manually sets `isInitialized=true` via type cast. Used in tests that need a fully-initialized manager before testing subsequent behavior.

## Test Coverage by Category

### Start / launch (L108–317)
- **Launches proxy and sends init command** (L108–120): verifies `launchProxySpy` called and `sendCommand` called with `{cmd:'init', sessionId, dryRunSpawn:true}`.
- **Rejects if proxy already running** (L122–126): sets `proxyProcess` directly, expects `'Proxy already running'`.
- **Dry-run snapshot recording** (L128–195): tests `getDryRunSnapshot()` for `adapter_configured_and_launched` status; verifies command string assembly from `adapterCommand.command + args`, fallback to `executablePath`, and filtering of non-string command values.
- **Adapter environment validation failure** (L231–258): `validateEnvironment` returns `valid:false`; expects throw matching `/Invalid environment.*Missing Python runtime/`.
- **Executable resolution failure** (L260–287): `resolveExecutablePath` rejects; expects rethrow.
- **Issue #106 — validates configured interpreter, not auto-detected** (L289–317): when `executablePath` is provided, `validateEnvironment` is called with it and `resolveExecutablePath` is NOT called.

### Init retry handling (L319–391)
Uses `vi.useFakeTimers()`. `beforeEach`/`afterEach` manage timer lifecycle.
- **Retries after transient send failure** (L328–362): first call throws, second succeeds; expects `sendCommand` called twice and warn log for attempt 1.
- **Exhausts retries with detailed error** (L364–390): all 6 attempts throw; advances 16.5s; expects error `/Failed to initialize proxy after 6 attempts\. Last error: ipc failure/`; manually sets `lastExitDetails`.

### Timeout (L393–420)
- **Times out when proxy never signals readiness** (L393–420): `dryRunSpawn:false`, only `init_received` sent (no `adapter_configured_and_launched`); advances 30s; expects `/Debug proxy initialization did not complete within 30s/`.

### Dry-run exit handling (L422–438)
- **Resolves when dry-run proxy exits cleanly** (L422–439): exit with code 0 after `init_received`; expects resolve.

### Stderr capture & error enrichment (L441–685)
- **Rejects with captured stderr on exit during init** (L441–463): uses fake timers; emits stderr data then `exit(2,'SIGTERM')`; expects error containing `Proxy exit details -> code=2 signal=SIGTERM stderr:\nboot failure`.
- **Caps stderr to last 10 of N lines, redacts secrets (issue #146)** (L465–500): 15 lines + PAT token; error contains `(last 10 of 15 lines)`, includes `stderr-line-06..14`, excludes `stderr-line-01..05` and `github_pat_supersecret`.
- **Truncates oversized stderr tail (~2000 char cap, issue #146)** (L502–535): 12 lines × ~300 chars; error contains `…`, `stderrPortion.length < 2200`, `MARKER-12` present, `MARKER-03` absent.
- **Buffer bounded at 100 lines (issue #146)** (L537–567): 150 lines emitted; error label `(last 10 of 100 lines)`, `line-150` present, `line-140` absent.
- **Redacts secret straddling chunk boundary (issue #151)** (L569–600): PAT split across two `data` events; error contains `[REDACTED — line contained sensitive data]`, no partial secret.
- **Per-line sanitization of multi-line chunks (issue #151)** (L602–631): benign line + secret line in one chunk; benign line survives, secret line redacted.
- **Flushes trailing partial line on stream `end` (issue #151)** (L633–658): no trailing newline before `end`; error contains `'fatal: adapter exploded'`.
- **Partial line flushed after exit appears in exit details (issue #151)** (L660–685): `end` fires after `exit`; error contains `late boot failure`.

### Script path validation (L687–693)
- **Fails when bootstrap script missing**: `pathExists` returns false; expects `/Bootstrap worker script not found/`.

### PID validation (L695–702)
- **Throws when launcher returns process without pid**: expects `'Proxy process is invalid or PID is missing'`.

### `findProxyScript` resolution (L704–766)
Parameterized via `createManagerWithModuleUrl` helper (L705–723) that passes a `runtimeEnv` override.
- **Module under `dist/`** (L725–734): resolves to `dist/proxy/proxy-bootstrap.js`.
- **Module under `dist/proxy/`** (L736–745): same target path.
- **Module outside dist (development layout)** (L747–756): falls back to `dist/proxy/proxy-bootstrap.js` relative to module dir.
- **Script missing throws** (L758–765): `pathExists=false`; expects `/Bootstrap worker script not found/`.

### Stop and cleanup (L768–828)
- **Force kill on timeout** (L769–791): fake timers; `send({cmd:'terminate',...})` then `kill('SIGKILL')` after 5s; warn log.
- **Immediate resolve if already killed** (L793–803): `killed=true`; no send/kill.
- **Cleanup rejects pending requests and clears barrier** (L805–827): inserts pending DAP request and active barrier; calls `cleanup()`; pending request rejected, barrier disposed, map empty.

### `sendCommand` diagnostics (L830–896)
- **Throws when proxy unavailable** (L831–835): `proxyProcess=null`.
- **Logs pre/post IPC details and transport errors** (L838–859): checks `logger.info` for dispatch log, `logger.error` for failure log with pid.
- **Logs exit details when sending after exit** (L861–880): `killed=true` + `lastExitDetails` set; expects error log containing `Attempted to send command after proxy unavailable. Last exit`.
- **Generic availability error without exit details** (L882–895): `lastExitDetails=undefined`.

### IPC telemetry (L898–933)
- **Logs IPC telemetry and heartbeat events from `setupEventHandlers`** (L898–933): emits `ipc-send-start`, `ipc-send-complete`, `ipc-send-failed`, `ipc-send-error` events and heartbeat messages; verifies `logger.debug`, `logger.warn`, `logger.error` output.

### `handleProxyExit` (L935–980)
- **Synthesizes dry-run completion on clean exit without prior notification** (L936–949): emits `dry-run-complete` event, `hasDryRunCompleted()` returns true.
- **Rejects pending requests and emits exit event for non-dry-run** (L951–979): pending DAP request rejected, `exit` event emitted, `activeLaunchBarrier` cleared.

### Launch barrier integration (L982–1014)
- **Fire-and-forget barrier in `sendDapRequest`** (L983–1013): `awaitResponse=false`; response is `{}`, `onRequestSent`/`waitUntilReady`/`dispose` called.

### DAP request lifecycle (L1016–1310)
- **Forwards status events** (L1016–1036): `dry-run-complete` listener receives forwarded payload.
- **Lifecycle events from adapter-driven statuses** (L1038–1110): calls `prepareSpawnContext`, then manually fires `handleStatusMessage` for `dry_run_complete`, `adapter_configured_and_launched`, `adapter_exited`; verifies `dry-run-complete`, `initialized`, `adapter-configured`, `exit` events.
- **Resolves DAP responses and captures thread ids** (L1112–1149): `sendDapRequest('threads')` resolves; `getCurrentThreadId()` returns 77; pending map cleared.
- **Rejects DAP requests on proxy error** (L1151–1175): `success:false` response; expects throw.
- **Rejects on timeout** (L1177–1198): fake timers, 35s advance; `/Debug adapter did not respond to 'continue'/`.
- **Propagates transport errors and clears pending** (L1200–1210): `sendCommand` throws; pending map cleared.
- **Rejects pending DAP on proxy exit** (L1212–1230): `exit` event clears pending with `'Proxy exited'`.
- **Rejects initialization on non-zero exit before readiness** (L1232–1257): fake timers; exit(7) + retries; `/Failed to initialize proxy after \d+ attempts/`.
- **Rejects initialization on signal exit** (L1259–1284): exit(null, 'SIGTERM') + retries.

### Concurrent stop / post-stop (L1286–1345)
- **Multiple concurrent stops without error** (L1286–1298): two simultaneous `stop()` calls; both resolve undefined, no kill.
- **Prevents new DAP after stop** (L1300–1310): post-stop `sendDapRequest` throws `'Proxy not initialized'`.
- **Stop while start pending** (L1312–1335): fake timers; start + stop concurrent; stop resolves, start rejects `/Proxy/`.
- **Resolves stop when proxy already exited** (L1337–1345).

## `ProxyManager helpers` suite (L1348–1493)
Tests `findProxyScript` (dev mode path, bundled path) and `prepareSpawnContext` (successful resolution, validation failure).

## Architecture Notes
- All internal state (`proxyProcess`, `isInitialized`, `sessionId`, `dapState`, `lastExitDetails`, `pendingDapRequests`, `isDryRun`, `activeLaunchBarrier`, etc.) is accessed via `as unknown as {...}` type casts — ProxyManager fields are not publicly exposed.
- `ProxyManager` constructor signature: `(adapter | null, proxyProcessLauncher, fileSystem, logger, runtimeEnv?)`.
- Tests drive async flows using a combination of `process.nextTick`, `setTimeout`, `setImmediate`, and `vi.advanceTimersByTimeAsync`.