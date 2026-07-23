# tests\unit\adapters\javascript-debug-adapter.test.ts
@source-hash: 1718df301d9860cf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:58Z


## Unit Tests: JavascriptDebugAdapter Runtime Helpers

Tests for the `JavascriptDebugAdapter` class from the `@debugmcp/adapter-javascript` package, covering error translation, feature support flags, and launch barrier lifecycle.

### Test Suite: `JavascriptDebugAdapter runtime helpers` (L17–48)

Instantiates the adapter via `createDependencies()` (L5–15) — a factory producing stub injections with `vi.fn()` mocks for the logger and empty objects for `fileSystem`, `environment`, and `networkManager`.

#### Test Cases

**`translateErrorMessage` — ENOENT handling (L18–22)**
Passes a Node.js spawn error (`ENOENT: spawn node ENOENT`) to `adapter.translateErrorMessage(...)` and asserts the returned string contains `'Node.js runtime not found'`. Validates that missing-runtime errors surface actionable user guidance.

**`supportsFeature` — feature flag matrix (L24–29)**
Asserts:
- `DebugFeature.CONDITIONAL_BREAKPOINTS` → `true`
- `DebugFeature.EVALUATE_FOR_HOVERS` → `true`
- `DebugFeature.DATA_BREAKPOINTS` → `false`

**Launch barrier — full lifecycle for `'launch'` command (L31–42)**
- `adapter.createLaunchBarrier('launch')` returns a defined barrier object.
- `barrier.awaitResponse` is `false`.
- Calls `barrier.onRequestSent('request-123')`, then creates `barrier.waitUntilReady()` promise.
- Fires `barrier.onDapEvent('stopped', undefined)`.
- Asserts the `waitUntilReady()` promise resolves to `undefined` (i.e., the barrier unblocks on a `'stopped'` DAP event).
- Calls `barrier.dispose()` for cleanup.

**Launch barrier — non-launch command (L44–47)**
- `adapter.createLaunchBarrier('threads')` returns `undefined`, confirming the barrier is only created for `launch`-type commands.

### Key Dependency: `createDependencies` (L5–15)
Shared factory for all tests. Provides:
- `logger`: all methods mocked with `vi.fn()`
- `fileSystem`: empty object `{}`
- `environment`: empty object `{}`
- `networkManager`: empty object cast via `as unknown`

### Cross-File Contracts
- `JavascriptDebugAdapter` imported from `packages/adapter-javascript/src/javascript-debug-adapter.js` (L2)
- `DebugFeature` enum imported from `@debugmcp/shared` (L3); values used: `CONDITIONAL_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `DATA_BREAKPOINTS`
- Barrier API surface tested: `.awaitResponse`, `.onRequestSent(id)`, `.waitUntilReady()`, `.onDapEvent(event, data)`, `.dispose()`
