# tests\unit\proxy\dap-proxy-core.test.ts
@source-hash: f3989668adde0c5e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:45Z

## Unit Tests for `dap-proxy-core.ts`

Tests for `ProxyRunner`, `detectExecutionMode`, and `shouldAutoExecute` from the DAP proxy core module. All tests use an injected `FakeCurrentProcess` to avoid touching the global `process` object, preventing listener leaks into the vitest fork worker (issues #159 and #183).

### Test Suite Structure

**`ProxyRunner` (L55–141)**
- Basic lifecycle: construction, initial state (`UNINITIALIZED`), worker retrieval, `start()` / `stop()` semantics
- `start()` logs "Ready to receive commands" (L99–101); throws "already running" if called twice (L107)
- `stop()` is idempotent before `start()` (L110–114); logs "Stopped" after `start()` (L121–123)
- Custom `onMessage` callback accepted but not triggered without IPC/stdin (L126–140)

**`detectExecutionMode` (L147–167)**
- `hasIPC: true` when `proc.send` is a function (L149)
- `hasIPC: false` when `proc.send` is undefined (L154)
- `isWorkerEnv: true` when `env.DAP_PROXY_WORKER === 'true'` (L159)
- `isWorkerEnv: false` when env var is unset (L164)

**`shouldAutoExecute` (L173–189)**
- Returns `true` if any of `isDirectRun`, `hasIPC`, `isWorkerEnv` is true
- Returns `false` only when all three flags are false

**`ProxyRunner IPC communication` (L195–379)**
- Verifies listener setup on `message`, `disconnect`, `error` events (L213–220)
- String messages passed directly to `onMessage`; object messages stringified via `JSON.stringify` (L222–244)
- **Security tests (issue #146)**: confirms `adapterCommand.env` and `launchConfig.env` values never appear in any log output — even when message processing fails (L246–327)
- Unexpected message types (non-string, non-object) trigger `logger.warn` with "unexpected type" (L329–341)
- Each processed message triggers an `ipc-heartbeat` acknowledgement sent back via `proc.send` (L343–356)
- `disconnect` event triggers worker shutdown and `proc.exit(0)` (L358–367)
- `error` event logs "IPC channel error" (L369–378)

**`ProxyRunner stdin communication` (L385–442)**
- Logs "stdin/readline" when stdin mode activated (L403–409)
- Stdin EOF (via `fakeProc.stdin.end()`) triggers worker shutdown, "stdin closed" warning, and `proc.exit(0)` (L412–427)
- Calling `stop()` explicitly closes the readline interface without triggering the stdin-closed exit path (L429–441)

**`ProxyRunner heartbeat and init timeout` (L448–530)** — uses `vi.useFakeTimers()`
- Heartbeat tick sent every 5 000 ms via `proc.send({ type: 'ipc-heartbeat-tick', counter: N })` (L468–483)
- Failed heartbeat send (ERR_IPC_CHANNEL_CLOSED) causes warn "parent unreachable", shutdown, and `proc.exit(1)` (L485–506)
- Init timeout fires after exactly 10 000 ms with no IPC/stdin, logging "No initialization received" and calling `proc.exit(1)` (L508–518)
- Init timeout does NOT fire at 9 999 ms (L521–528)

**`ProxyRunner.setupGlobalErrorHandlers` (L536–619)**
- Registers four listeners: `uncaughtException`, `unhandledRejection`, `SIGTERM`, `SIGINT` (L550–561)
- `uncaughtException`: sends `{ type: 'error', sessionId }` via `messageSender.send`, calls `shutdownFn`, exits with 1 (L563–578)
- `unhandledRejection`: sends `{ type: 'error', sessionId: 'unknown' }` but does NOT call `proc.exit` (L580–593)
- `SIGTERM` / `SIGINT`: both call `shutdownFn` and `proc.exit(0)` (L595–619)

### Key Helpers

- `createMockDependencies()` (L18–40): builds a full `DapProxyDependencies` stub with vi.fn() mocks for `loggerFactory`, `fileSystem`, `processSpawner`, `dapClientFactory`, `messageSender`
- `createMockLogger()` (L42–49): returns an `ILogger` stub with vi.fn() for info/error/debug/warn

### Dependencies
- `FakeCurrentProcess` from `../../test-utils/mocks/fake-current-process.js` — controllable EventEmitter-based process substitute; `.disableIPC()` removes `send`; `.failSendWith(err)` makes send throw; `.lastListener(event)` retrieves most-recently-registered handler; `.stdin.end()` simulates EOF
- `ProxyRunner`, `detectExecutionMode`, `shouldAutoExecute` from `../../../src/proxy/dap-proxy-core.js`
- `ProxyState` enum from `../../../src/proxy/dap-proxy-interfaces.js`

### Patterns
- All `runner` instances cleaned up via `afterEach` → `runner.stop()` (L68–72, L207–210, etc.)
- Fake timers (`vi.useFakeTimers()`) scoped to the heartbeat/timeout suite only (L455, L462)
- Microtask/macrotask draining via `await new Promise(r => setTimeout(r, 10))` for async side-effects triggered by event emission
