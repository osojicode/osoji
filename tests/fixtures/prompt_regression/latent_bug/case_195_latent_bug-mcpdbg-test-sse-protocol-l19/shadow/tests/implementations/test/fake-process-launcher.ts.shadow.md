# tests\implementations\test\fake-process-launcher.ts
@source-hash: dc17d0c5d85dc373
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:46Z

## Test Fake Process Launcher Implementations

Provides deterministic, in-memory fakes for `IProcess`, `IProxyProcess`, and `IProxyProcessLauncher` interfaces, enabling unit tests to control process lifecycle, IPC messages, and initialization flows without spawning real OS processes.

---

### `FakeProcess` (L18–86) — extends `EventEmitter`, implements `IProcess`

Base fake process. Streams (`stdin`, `stdout`, `stderr`) are `PassThrough` instances. Fixed `pid = 12345`.

**State fields:**
- `_killed` (L24) — set `true` on `kill()` or `simulateExit()`
- `_exitCode` (L25) — set by `simulateExit()`
- `_signalCode` (L26) — set by `kill()` or `simulateExit()`

**IProcess methods:**
- `send(message)` (L40–45): emits `'message'` on next tick unless killed; returns `false` if killed.
- `kill(signal='SIGTERM')` (L47–56): sets `_killed`, emits `'exit'` and `'close'` on next tick; returns `false` if already killed.

**Test-control helpers:**
- `simulateOutput(data)` (L59–61): pushes data to `stdout` stream.
- `simulateError(data)` (L63–65): pushes data to `stderr` stream.
- `simulateExit(code, signal?)` (L67–73): synchronously emits `'exit'` and `'close'`; sets `_killed = true`.
- `simulateSpawn()` (L75–77): emits `'spawn'` on next tick.
- `simulateProcessError(error)` (L79–81): emits `'error'`.
- `simulateMessage(message)` (L83–85): emits `'message'`.

---

### `FakeProxyProcess` (L91–126) — extends `FakeProcess`, implements `IProxyProcess`

Adds proxy-level IPC concerns on top of `FakeProcess`.

**Constructor:** accepts `sessionId: string` (L94), stored as `readonly`.

**Public fields:**
- `sentCommands: object[]` (L92) — accumulates every command passed to `sendCommand()`.

**IProxyProcess methods:**
- `sendCommand(command)` (L98–102): appends to `sentCommands`, JSON-stringifies, forwards to inherited `send()`.
- `waitForInitialization(timeout=30000)` (L104–107): immediately resolves; no real waiting.

**Test-control helpers:**
- `simulateInitialization()` (L110–116): emits a `{ type: 'status', status: 'adapter_configured_and_launched', sessionId }` message.
- `simulateInitializationFailure(error)` (L119–125): emits a `{ type: 'error', sessionId, message: error }` message.

---

### `FakeProxyProcessLauncher` (L131–194) — implements `IProxyProcessLauncher`

Factory that creates and tracks `FakeProxyProcess` instances.

**Public fields:**
- `launchedProxies` (L132–137): array of `{ proxyScriptPath, sessionId, env?, process }` records for each `launchProxy()` call.

**Private fields:**
- `nextProxy` (L139): if set by `prepareProxy()`, the next `launchProxy()` uses this instance instead of creating a new one.

**`launchProxy(proxyScriptPath, sessionId, env?)` (L141–174):**
- Uses `nextProxy` if set (clears it after); otherwise creates `new FakeProxyProcess(sessionId)`.
- Records call in `launchedProxies`.
- Calls `proxy.simulateSpawn()`.
- For non-prepped proxies: monkey-patches `sendCommand` so that when a command with `cmd === 'init'` is received, a `{ type: 'status', status: 'init_received', sessionId }` message is auto-emitted on next tick (L155–170). **Note:** prepped proxies receive no such auto-response.

**Test-control helpers:**
- `prepareProxy(setup)` (L177–181): creates a `FakeProxyProcess('test-session')`, runs caller-supplied `setup` callback on it, stores as `nextProxy`.
- `getLastLaunchedProxy()` (L184–187): returns `launchedProxies[last].process` or `undefined`.
- `reset()` (L190–193): clears `launchedProxies` and `nextProxy`.

---

### Key Behavioral Contracts

| Scenario | Trigger | Response |
|---|---|---|
| Process spawn | `launchProxy()` or `simulateSpawn()` | `'spawn'` event on next tick |
| Init handshake (default proxy) | `sendCommand({ cmd: 'init', ... })` | `status: 'init_received'` message on next tick |
| Full initialization | `simulateInitialization()` | `status: 'adapter_configured_and_launched'` message |
| Exit | `kill()` or `simulateExit()` | `'exit'` + `'close'` events |

### Important Asymmetries
- `simulateExit()` emits **synchronously**; `kill()` emits **on next tick**.
- `waitForInitialization()` is a no-op stub — tests that need real init sequencing must call `simulateInitialization()` manually (unless the auto-response from `launchProxy()` triggers it via the real implementation).
- `prepareProxy` hardcodes `sessionId = 'test-session'` (L178); this may not match the `sessionId` passed to `launchProxy()`.
