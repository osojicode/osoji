# tests\unit\implementations\process-launcher-impl.test.ts
@source-hash: 54f3b054c7c36f3f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:26Z

## Purpose
Unit tests for `ProxyProcessLauncherImpl`, covering proxy process lifecycle: initialization resolution, early-exit rejection, environment scrubbing, container detection, concurrent initialization deduplication, kill-during-wait, and kill-exception handling.

## Test Fixture Setup (L7–34)

### `FakeChildProcess` (L7–22)
Extends `EventEmitter` and implements `IChildProcess`. Provides:
- `pid?: number` (L8), `killed = false` (L9), `stdin/stdout/stderr` streams (L10–12)
- `stderr` initialized to `new PassThrough()` (L17)
- `kill` and `send` as `vi.fn()` mocks (L20–21)
- Constructor accepts optional `pid` (L14), sets `pid` and `stderr`

### `beforeEach` (L28–34)
Creates a fresh `FakeChildProcess(2222)` and a mock `IProcessManager` with:
- `spawn`: `vi.fn().mockReturnValue(child)` — returns the fake child
- `exec`: `vi.fn()`

## Test Cases

| Test | Lines | What's Verified |
|---|---|---|
| Resolves initialization on `adapter_configured_and_launched` message | L36–45 | `waitForInitialization(1000)` resolves to `undefined` when child emits `{ type: 'status', status: 'adapter_configured_and_launched' }` |
| Rejects on early exit | L47–56 | `waitForInitialization(100)` rejects with `/exited/` when child emits `exit` event |
| Throws on failed `send` | L58–65 | `sendCommand({ foo: 'bar' })` throws `/Failed to send/` when `child.send` returns `false` |
| Scrubs test env vars | L67–80 | `NODE_ENV`, `VITEST`, `JEST_WORKER_ID` are removed from spawn options `env` when present |
| Container disables detach | L82–92 | `options.detached === false` when `MCP_CONTAINER=true` |
| Reuses initialization promise | L94–111 | `createInitializationPromise` called only once for concurrent `waitForInitialization` calls; subsequent calls after resolution resolve immediately |
| Kill during wait fails init | L113–125 | `kill('SIGTERM')` returns `true` and pending `waitForInitialization` rejects with `/Process killed during initialization/`; subsequent call rejects with `/already completed or failed/` |
| Pre-wait exit fails init | L127–134 | If child exits before `waitForInitialization` is called, the call rejects with `/already completed or failed/` |
| Kill throwing returns false | L136–146 | When `child.kill` throws, `proxyProcess.kill(...)` returns `false` |

## Key Behavioral Contracts Verified
1. **Initialization message discrimination**: only `{ type: 'status', status: 'adapter_configured_and_launched' }` resolves (L42)
2. **Promise deduplication**: internal `createInitializationPromise` private method is spied upon to verify single creation (L98)
3. **Environment isolation**: three specific env vars (`NODE_ENV`, `VITEST`, `JEST_WORKER_ID`) are stripped before spawning the proxy (L77–79)
4. **Container detection**: `MCP_CONTAINER` env var controls `detached` spawn option (L83, L91)
5. **State machine**: once failed/completed, further `waitForInitialization()` calls throw immediately (L124, L133)

## Dependencies
- `ProxyProcessLauncherImpl` from `src/implementations/process-launcher-impl.js` — the SUT
- `IChildProcess`, `IProcessManager` from `@debugmcp/shared` — interfaces used for fixtures
- `vitest` (`describe`, `it`, `expect`, `beforeEach`, `vi`) — test framework
- `EventEmitter` from Node.js `events` — base for `FakeChildProcess`
- `PassThrough` from Node.js `stream` — fake stderr stream
