# packages\shared\src\utils\line-buffer.ts
@source-hash: 7f3529f9fad54fac
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:33Z

## LineBuffer (L11–42)

Incremental newline splitter for streamed output. Designed to ensure content-based filters (e.g. secret redaction on stderr) always operate on complete lines, not arbitrary byte chunks. Addresses issue #151 where a pattern split across two chunks could evade filters.

### Class: `LineBuffer` (L11–42)

**State:**
- `pending: string` (L12) — holds the partial (unterminated) line accumulated between appends.

**Constructor** (L19):
- `maxPendingLength` (default `8192`) — memory safety bound: if the pending buffer exceeds this length without a newline, it is flushed as a complete line to prevent unbounded memory growth.

### Methods

#### `append(chunk: string): string[]` (L22–32)
- Appends chunk to `pending`, splits on `\n`.
- All complete lines (all but the last segment) are returned; last segment stays in `pending`.
- CR (`\r`) is stripped from line endings (handles CRLF streams), via `line.endsWith('\r') ? line.slice(0, -1) : line` (L26).
- If `pending.length > maxPendingLength` after splitting (L27–30), the pending partial is emitted immediately and `pending` is reset to `''`.
- Returns `string[]` of complete lines (may be empty if no newline in chunk).

#### `flush(): string[]` (L35–42)
- Should be called when the stream ends.
- Returns `[pending]` if non-empty, clearing `pending`; returns `[]` if nothing is buffered.
- Ensures the final unterminated line is not silently dropped.

### Usage Pattern
```
const buf = new LineBuffer();
stream.on('data', chunk => {
  for (const line of buf.append(chunk)) processLine(line);
});
stream.on('end', () => {
  for (const line of buf.flush()) processLine(line);
});
```

### Key Invariants
- `pending` never contains `\n` after `append` (split + pop ensures this).
- `flush` is idempotent after the first call (returns `[]` on subsequent calls).
- CR stripping only applies to lines terminated by `\n`; partial lines emitted via `maxPendingLength` overflow or `flush` are returned as-is (no CR stripping on partials).
