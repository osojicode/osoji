# tests\unit\utils\safe-file-transport.test.ts
@source-hash: 1a41484653e0dbb4
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:02Z

## Purpose
Unit tests for `SafeFileTransport` (issue #121), verifying rotation-failure handling, no-busy-spin latch behavior, warning deduplication, and console-silencing. Uses **real winston** (no module mock) to exercise the private `_incFile` seam.

## Key Design Decisions
- **Real winston, no module mock** (L4-7): Tests are explicitly designed to break loudly if a winston upgrade renames `_incFile`, serving as a compatibility canary.
- **Fault injection via `vi.spyOn` on `winston.transports.File.prototype._incFile`** (L36-45): Simulates Windows EPERM rotation failure deterministically, without OS-level file locking.
- **Temp directory per test** (L53-54): Each test gets an isolated `fs.mkdtempSync` dir; cleanup in `afterEach` closes transport handles before `rmSync` (L57-81).
- **Transport teardown via `'closed'` event** (L62-72): Waits for graceful close with a 1-second timeout fallback (`setTimeout(...).unref?.()`) to avoid hanging on Windows.

## Test Fixtures & Helpers

### `makeEpermError()` (L27-33)
Returns a `NodeJS.ErrnoException` with `code: 'EPERM'` and message `'EPERM: operation not permitted, rename'`.

### `injectRotationFailure()` (L36-45)
Spies on `winston.transports.File.prototype._incFile`, making it immediately invoke its callback with an EPERM error. Returns the spy for call-count assertions.

### `makeTransport()` (L83-92)
Creates a `SafeFileTransport` with `maxsize: 1024`, `maxFiles: 3`, `tailable: true`, registers it in the `transports[]` teardown array, and returns it.

## Test Cases

### `'latches rotation off after a rotation failure and keeps appending (no busy-spin)'` (L94-121)
- Pre-fills file with 2× MAXSIZE content to trigger rotation on open.
- Injects EPERM rotation failure.
- Asserts: log message eventually written to file (L106-113); `_incFile` called exactly once (L116); `transport.rotationDisabled === true` (L117); `transport.maxsize === 0` (L118); file size > MAXSIZE (L120).

### `'does not interfere with successful rotation'` (L123-145)
- Pre-fills file with 2× MAXSIZE content; no rotation failure injected.
- Asserts: rotated file `test1.log` exists (L133); new log message appears in base file (L134-136); `transport.rotationDisabled === false` (L141); `transport.maxsize === MAXSIZE` (L142); rotated file size ≥ 2× MAXSIZE (L144).

### `'warns exactly once, and only when console output is not silenced'` (L147-169)
- Injects rotation failure; spies on `console.error`.
- Asserts: exactly 1 `console.error` call containing `'Log rotation failed'` (L163); message contains filename `'test.log'` (L164).
- Manually triggers `_incFile` again (L167) to verify second failure does NOT produce another warning (L168).

### `'stays silent on rotation failure when console output is silenced'` (L171-189)
- Stubs `process.env.CONSOLE_OUTPUT_SILENCED = '1'` (L172).
- Asserts: zero `console.error` calls containing `'Log rotation failed'` (L184-188).

## Dependencies
- `SafeFileTransport` from `../../../src/utils/safe-file-transport.js` — class under test; exposes `rotationDisabled` and `maxsize` public properties.
- `winston` — real (non-mocked); `winston.transports.File.prototype._incFile` is the private seam being pinned.
- `fs`, `os`, `path` — Node stdlib for temp file management.
- `vitest` — test framework (`vi.spyOn`, `vi.waitFor`, `vi.stubEnv`).

## Key Invariants / Contracts Tested
- `transport.rotationDisabled` (boolean) becomes `true` after first EPERM and stays `true` (latch).
- `transport.maxsize` is set to `0` after rotation is disabled (disables future rotation triggers).
- `_incFile` called exactly once even if rotation would otherwise be re-triggered (no busy-spin).
- Console warning fires at most once and is gated on `CONSOLE_OUTPUT_SILENCED` env var not being `'1'`.
