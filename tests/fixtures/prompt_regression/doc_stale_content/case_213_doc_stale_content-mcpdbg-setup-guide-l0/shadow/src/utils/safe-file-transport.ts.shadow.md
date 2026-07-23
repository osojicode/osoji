# src\utils\safe-file-transport.ts
@source-hash: ef7184443a1c4046
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:19Z

## SafeFileTransport (L50–84)

A hardened Winston `File` transport subclass that survives Windows log-rotation failures by latching rotation off permanently after the first error, preventing the infinite busy-spin bug documented in issue #121.

### Problem Solved
Winston's tailable rotation (`_checkMaxFilesTailable` → `fs.rename`) fails on Windows with `EPERM`/`EBUSY` when the file is held open. Winston discards the error and retries immediately, causing:
- Infinite `stat`/`exists`/`rename` busy-spin on libuv threadpool (40–200% CPU)
- Unbounded memory growth from buffered write queue
- Zero log output

### Fix Mechanism
Overrides the private `_incFile(callback)` (L54–84) method on `winston.transports.File`:
1. Looks up the parent `_incFile` lazily via `winston.transports.File.prototype` (L55)
2. If parent method is absent (winston renamed it), calls `callback()` and returns safely (L56–60) — degrades gracefully to stock File transport behavior
3. On rotation error: sets `this.rotationDisabled = true` (L64), zeroes `this.maxsize` (L67) — because `_needsNewFile()` checks `this.maxsize && size >= this.maxsize`, zeroing it permanently disables rotation
4. Optionally logs the error to `console.error` unless `CONSOLE_OUTPUT_SILENCED === '1'` (L70–76)
5. Swallows the error by calling `callback()` without the error (L82), allowing `stat()` to reopen the base file and drain the write queue

### Key Properties
- `rotationDisabled` (L52): Public flag, `true` once rotation has been latched off; enables external observability/testing
- `maxsize`: Inherited from `winston.transports.File`; zeroed on first rotation failure to permanently disable the `_needsNewFile()` check

### Defensive Design
- `_incFile` parent lookup is lazy and type-guarded (L56–60): if winston internals change shape, class behaves like stock `File` transport
- Pinned to `winston: ^3.19.0` — `_incFile` is stable across winston 3.x
- Unit tests in `tests/unit/utils/safe-file-transport.test.ts` verify the seam

### Known/Accepted Edge Case
Per-process log files named `debug-mcp-server-<pid>.log` — tailable rotation appends a digit to basename, which can collide with a live file for pid N×10+1. Consequence is at worst a failed rename, which this latch handles gracefully.

### Environment Variable Contract
- `CONSOLE_OUTPUT_SILENCED=1` (L70): Suppresses the `console.error` warning to avoid corrupting stdio transports (same guard used in `src/utils/logger.ts`)