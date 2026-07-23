# tests\unit\utils\safe-file-transport.test.ts
@source-hash: 1a41484653e0dbb4
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:47Z

## Purpose
Unit tests for `SafeFileTransport` (tracking issue #121). Exercises the rotation-failure latch by spying on winston's private `_incFile` internal, injecting EPERM errors, and asserting correct behavior: no busy-spin, single warning emission, silence when env-suppressed, and non-interference with successful rotation.

## Key Design Decisions

### Real Winston (No Module Mock) (L1-12)
Tests intentionally use real `winston` (not mocked) so that any winston upgrade that renames/reshapes `_incFile` will cause `vi.spyOn` to throw — a deliberate canary. This makes the suite tightly coupled to winston internals by design.

### Rotation Failure Injection (L36-45)
`injectRotationFailure()` spies on `winston.transports.File.prototype._incFile` and replaces it with a callback-based mock that immediately calls back with an EPERM error, simulating Windows file locking behavior without OS-level involvement.

### `makeEpermError()` (L27-33)
Constructs a `NodeJS.ErrnoException` with `code = 'EPERM'` and a message matching `'EPERM: operation not permitted, rename'`.

### Transport Lifecycle Management (L50-81)
Transports are pushed to a shared `transports[]` array (L50) in `makeTransport()` (L83-92). `afterEach` drains this array, closing each transport and waiting for the `'closed'` event with a 1-second timeout safety net (`setTimeout(...).unref?.()` — optional chaining guards against environments lacking `.unref()`). Then restores mocks, unstubs envs, and removes the temp directory.

## Test Cases

### `latches rotation off after failure` (L94-121)
- Pre-fills file beyond `MAXSIZE` (2×) to trigger rotation at open
- Injects EPERM rotation failure + silences `console.error`
- Asserts log message eventually appears in file (proves no busy-spin)
- Asserts `_incFile` called exactly once (latch prevents retry loop)
- Asserts `transport.rotationDisabled === true` and `transport.maxsize === 0`
- Asserts file size grew beyond `MAXSIZE` (appending continued)

### `does not interfere with successful rotation` (L123-145)
- Pre-fills file; no failure injection
- Asserts rotated file `test1.log` is created and new messages appear in base file
- Asserts `rotationDisabled === false` and `maxsize === MAXSIZE`
- Asserts rotated file contains the oversize original content

### `warns exactly once` (L147-169)
- Injects failure, waits for `rotationDisabled` to become `true`
- Filters `console.error` calls for `'Log rotation failed'` — expects exactly 1
- Verifies the warning message contains the filename (`test.log`)
- Calls `_incFile` manually a second time; confirms warning count stays at 1

### `stays silent when CONSOLE_OUTPUT_SILENCED=1` (L171-189)
- Stubs `process.env.CONSOLE_OUTPUT_SILENCED = '1'`
- Injects failure, waits for `rotationDisabled`
- Asserts zero `'Log rotation failed'` console errors

## Constants
- `MAXSIZE = 1024` (L25) — rotation threshold used for all transport instances

## Types
- `IncFileCallback` (L20): `(err?: Error | null) => void`
- `FileTransportInternals` (L21-23): Interface augmenting `winston.transports.File.prototype` with `_incFile`

## Critical Invariants
- `transport.rotationDisabled` and `transport.maxsize` are public properties on `SafeFileTransport` that these tests assert directly
- The `_incFile` method must exist on `winston.transports.File.prototype` — if removed by a winston upgrade, spy setup fails loudly
- `CONSOLE_OUTPUT_SILENCED` env var controls whether `SafeFileTransport` emits `console.error` on rotation failure