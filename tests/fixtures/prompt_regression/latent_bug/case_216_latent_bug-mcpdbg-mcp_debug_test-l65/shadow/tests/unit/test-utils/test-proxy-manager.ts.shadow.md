# tests\unit\test-utils\test-proxy-manager.ts
@source-hash: fbddf8b10c6fada3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:58Z

## Test Utility: TestProxyManager

`TestProxyManager` (L13–162) is a test double for `ProxyManager` used in unit tests. It extends the real `ProxyManager` but overrides complex async/process-based initialization to enable synchronous, deterministic testing without spawning real child processes.

### Key Class: TestProxyManager (L13–162)

**Extends:** `ProxyManager` from `src/proxy/proxy-manager.js`

**Private/Public State:**
- `mockResponses: Map<string, any>` (L14) — pre-configured DAP command responses
- `simulatedThreadId: number | null` (L15) — tracks simulated thread state
- `lastSentCommand: any` (L16, public) — records the most recent DAP command sent; useful for assertions

**Constructor (L18–27):**
- Accepts optional `logger` (defaults to `createMockLogger()`) and `fileSystem` (defaults to `createMockFileSystem()`)
- Passes `null` for both `launcher` and the second `null as any` arg to super, bypassing real process launching
- Manually initializes `(this as any).pendingRequests` as a new `Map` for cleanup testing

**Overridden Methods:**

- `start(config: ProxyConfig): Promise<void>` (L32–44): Sets `sessionId`, marks `isInitialized = true`, sets fake `proxyProcess = { pid: 12345 }`, dynamically imports and calls `createInitialState` to set up `dapState`, then emits `'initialized'`. No real process is launched.

- `stop(): Promise<void>` (L49–63): Clears `isInitialized`, `proxyProcess`, `dapState`, clears `pendingRequests` map, emits `'exit'`. Avoids rejecting pending requests (assumes they're already resolved).

- `sendDapRequest(command, args?, options?): Promise<DebugProtocol.Response>` (L68–105): Records command to `lastSentCommand`, checks `isRunning()`, returns mock response from `mockResponses` map or a default success response. Briefly inserts then removes a pending request entry via `process.nextTick` to simulate pending state for cleanup tests.

- `getCurrentThreadId(): number | null` (L152–154): Returns `simulatedThreadId`.

- `isRunning(): boolean` (L159–161): Returns `true` iff `proxyProcess !== null`.

**Test Helpers:**
- `setMockResponse(command, response)` (L110–112): Registers a response for a specific DAP command string.
- `simulateMessage(message)` (L117–131): Validates the message is a non-null object, injects `sessionId` if missing, then calls private `handleProxyMessage` via type cast.
- `simulateStoppedEvent(threadId, reason)` (L136–139): Sets `simulatedThreadId`, emits `'stopped'` event with threadId, reason, and empty object.
- `simulateContinuedEvent()` (L144–147): Resets `simulatedThreadId` to `null`, emits `'continued'` with empty object.

### Module-level Helpers

- `createMockLogger(): ILogger` (L167–174): Returns a no-op implementation of `ILogger` with `debug`, `info`, `warn`, `error` all as `() => {}`.
- `createMockFileSystem(): IFileSystem` (L179–188): Returns a stub `IFileSystem` where `pathExists` always resolves `true`, `readFile` returns `''`, `stat` returns an object with `isFile: () => true`, and all write/ensure operations are no-ops.

### Architectural Patterns
- Uses `(this as any)` casts extensively to access private members of the parent `ProxyManager` class — a common test double pattern in TypeScript when subclassing sealed or private-field classes.
- Dynamic import of `createInitialState` inside `start()` (L38) avoids circular import issues at module load time.
- Default parameter values (`createMockLogger()`, `createMockFileSystem()`) allow zero-config construction in most tests.