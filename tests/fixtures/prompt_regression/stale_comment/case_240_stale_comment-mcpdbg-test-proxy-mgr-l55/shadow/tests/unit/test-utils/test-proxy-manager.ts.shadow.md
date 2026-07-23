# tests\unit\test-utils\test-proxy-manager.ts
@source-hash: fbddf8b10c6fada3
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:02Z

## Test Utility: TestProxyManager

`TestProxyManager` (L13–162) is a test double for `ProxyManager` used in unit tests. It subclasses the real `ProxyManager` but overrides all I/O-heavy, async, and process-dependent methods to enable synchronous, deterministic, in-process testing without spawning actual debug adapter processes.

### Architecture

Extends `ProxyManager` with `null` passed for the launcher and `null as any` for a second positional arg (L23), bypassing real initialization. The `pendingRequests` map is manually initialized via cast (L26) to mirror the private field in the parent class.

### Key Overrides

| Method | Lines | Behavior |
|---|---|---|
| `start(config)` | L32–44 | Sets `sessionId`, marks `isInitialized`, fakes a `proxyProcess` with pid 12345, dynamically imports and initializes DAP state, emits `'initialized'` |
| `stop()` | L49–63 | Clears internal state flags, clears `pendingRequests`, emits `'exit'`, no actual process teardown |
| `sendDapRequest(cmd, args, opts)` | L68–105 | Records the call in `lastSentCommand`, checks `isRunning()`, returns pre-configured mock or default success response; briefly registers then cleans a `pendingRequests` entry via `process.nextTick` |
| `isRunning()` | L159–161 | Returns `true` iff `proxyProcess` is non-null |
| `getCurrentThreadId()` | L152–154 | Returns `simulatedThreadId` field instead of inspecting real DAP state |

### Test Simulation API

- **`setMockResponse(command, response)`** (L110–112): Pre-configures a response for a specific DAP command string, stored in `mockResponses` map (L14).
- **`simulateMessage(message)`** (L117–131): Injects an arbitrary message into the parent's private `handleProxyMessage` method via cast. Validates message is a non-null object; injects `sessionId` if missing.
- **`simulateStoppedEvent(threadId, reason)`** (L136–139): Sets `simulatedThreadId` and emits `'stopped'` with `(threadId, reason, {})`.
- **`simulateContinuedEvent()`** (L144–147): Clears `simulatedThreadId` and emits `'continued'` with `({})`.

### Public Observable State

- **`lastSentCommand`** (L16): Set to `{ command, args, ...options? }` on every `sendDapRequest` call; readable by tests to assert what was sent.

### Internal Helpers (module-private)

- **`createMockLogger()`** (L167–174): Returns an `ILogger` with all no-op methods.
- **`createMockFileSystem()`** (L179–188): Returns an `IFileSystem` with no-op async methods; `pathExists` always resolves `true`; `stat` returns `{ isFile: () => true }`.

### Dependencies

- `ProxyManager` from `src/proxy/proxy-manager.js` — real parent class.
- `ProxyConfig` from `src/proxy/proxy-config.js` — type for `start()` parameter.
- `IFileSystem`, `ILogger`, `IProxyProcessLauncher` from `@debugmcp/shared` — interfaces for mock implementations.
- `DebugProtocol` from `@vscode/debugprotocol` — type for `sendDapRequest` return.
- `createInitialState` from `src/dap-core/index.js` — dynamically imported in `start()` to construct real DAP state.

### Notable Patterns

- Private parent fields accessed via `(this as any)` casts (L26, L34–39, L51–53, L56, L86, L130) — tight coupling to parent implementation details.
- `start()` uses a dynamic `import()` for `createInitialState` (L38), making it async even in test context.
- `sendDapRequest` adds a `pendingRequests` entry and removes it via `process.nextTick` to simulate asynchronous pending state for cleanup-testing scenarios without actually blocking.
- Constructor default parameters provide zero-config instantiation for most tests (L19–20).
