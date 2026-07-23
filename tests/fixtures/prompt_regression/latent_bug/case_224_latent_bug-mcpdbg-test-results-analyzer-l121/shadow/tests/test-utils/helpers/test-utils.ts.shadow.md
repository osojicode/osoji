# tests\test-utils\helpers\test-utils.ts
@source-hash: 483de0e4ee0ad48e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:42Z

## Test Utilities for Debug MCP Server

Shared helper module providing reusable test infrastructure for vitest-based tests. Exports mock factories and async synchronization primitives used across the test suite.

### Exports

#### `delay(ms)` (L13–15)
Simple promise-based sleep. Wraps `setTimeout` in a `Promise<void>`. Used internally by `waitUntil` and available for tests needing a fixed pause.

#### `createMockLogger()` (L21–28)
Returns an `ILogger`-conformant object with all four methods (`info`, `error`, `warn`, `debug`) replaced by `vi.fn()` mocks. Callers can assert on call counts/arguments or configure return values via `.mockResolvedValue` / `.mockReturnValue`.

#### `createMockFileSystem()` (L34–53)
Returns an `IFileSystem`-conformant object (cast via `as any`) with all filesystem methods replaced by `vi.fn()` mocks. Default resolved values:
- `pathExists` / `exists` → `true`
- `readFile` → `''` (empty string)
- `stat` → `{ isDirectory: () => false, isFile: () => true }`
- All write/mutating methods → `undefined`
- `readdir` → `[]`
- `ensureDirSync`, `createWriteStream`, `createReadStream` → plain `vi.fn()` (synchronous/no default return)

#### `waitUntil(condition, options?)` (L70–87)
Polls an async or sync predicate until it returns truthy or a configurable timeout elapses. Options:
- `timeout` (default `5000` ms)
- `interval` (default `50` ms)
- `message` (default `'condition'`) — included in timeout error text

Checks the condition immediately on entry before waiting `interval`. Rejects with `Error: Timeout after ${timeout}ms waiting for ${message}` on timeout.

Preferred over fixed `delay()` sleeps for flake-resistant async test synchronization.

#### `waitForEvent<T>(emitter, event, timeout?)` (L97–116)
Returns a `Promise<T>` that resolves with the spread arguments of the first emission of `event` on `emitter`. Timeout defaults to `5000` ms; on timeout, cleans up via `emitter.removeListener` (if present) and rejects with `Error: Timeout waiting for event: ${event}`.

Accepts any object with an `once(event, handler)` method (duck-typed); `removeListener` is optional.

### Dependencies
- `IFileSystem`, `ILogger` — interface contracts from `src/interfaces/external-dependencies.js`; mock objects must satisfy their full method signatures
- `vi` from `vitest` — all mock functions are vitest mocks, compatible with `.toHaveBeenCalled()` etc.