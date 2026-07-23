# packages\shared\tests\unit\line-buffer.property.test.ts
@source-hash: 34afb126cce9f763
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:00Z

## Property-Based Tests for `LineBuffer`

**Purpose:** Verifies chunking invariance and memory bounds of `LineBuffer` using `fast-check` property-based testing. Guards the stderr sanitization path (issue #151) ensuring secret redaction filters always see whole lines regardless of OS stream chunking.

### Test File Structure

**Helpers:**

- `referenceSplit(input)` (L15–20): Reference model that splits an entire input string at once on `\n`, strips trailing `\r` from each line, and returns `{ lines, flushed }`. Used as the oracle for all property assertions.
- `chunkAt(input, cuts)` (L23–33): Splits a string into contiguous chunks at arbitrary cut positions (deduped, sorted, modulo `input.length + 1`). Simulates arbitrary OS stream chunking.
- `textWithNewlines` (L36–38): `fast-check` arbitrary for strings mixing plain text segments (up to 12 chars) with all three newline conventions (`\n`, `\r\n`, `\r`), up to 40 pieces joined together.

### Properties Tested

1. **Chunking invariance** (L41–56): For any input and any set of cut positions, the lines emitted by `LineBuffer.append()` across chunks plus `flush()` equal the lines produced by `referenceSplit`. Validates that stream fragmentation cannot split a line across two `append` calls in a way that breaks output.

2. **Flush idempotence and reuse** (L58–73): After a flush, a second flush returns `[]`. After flush, the buffer is fully reset — subsequent input to the same buffer instance produces identical output to a fresh `LineBuffer` instance.

3. **Newline-free memory bound** (L75–93): For streams with no newlines, no data is lost (all emitted + flushed content equals joined input), and the internal `pending` field never exceeds `maxPendingLength`. Accesses the private `pending` field via `(buffer as unknown as { pending: string }).pending` (L85) to assert the memory invariant.

### Key Design Notes

- Tests the `LineBuffer` constructor with and without the optional `maxPendingLength` parameter (L81).
- `referenceSplit` handles `\r\n` implicitly: splitting on `\n` first, then stripping trailing `\r` per line — this is the canonical behavior the `LineBuffer` must match.
- The `'\r'`-only newline convention in `textWithNewlines` is included but NOT handled by `referenceSplit`'s split-on-`\n` + strip-`\r` logic; bare `\r` without a following `\n` will NOT be treated as a line terminator by the reference model. This means `LineBuffer` must also treat bare `\r` as non-terminating for the invariant to hold.
- Private field access at L85 (`buffer as unknown as { pending: string }`) creates a cross-file coupling to `LineBuffer`'s internal field name `pending`.