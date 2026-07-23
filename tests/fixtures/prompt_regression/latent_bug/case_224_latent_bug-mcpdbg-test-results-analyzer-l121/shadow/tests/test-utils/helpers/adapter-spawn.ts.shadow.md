# tests\test-utils\helpers\adapter-spawn.ts
@source-hash: 3989efeaf1ee95aa
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:37Z

## Adapter Spawn-Failure Detection for E2E Smoke Tests

This utility module provides helpers for detecting environmental adapter spawn failures in end-to-end smoke tests. Its primary purpose is to **skip** tests (not hard-fail) when a language adapter's debug binary (e.g., CodeLLDB's `codelldb.exe`, Delve's `dlv`) cannot spawn due to missing binaries, permission issues, or OS-level policy blocks (e.g., Windows Smart App Control).

---

### Core Design Philosophy

Signatures in `SPAWN_BLOCKED_SIGNATURES` (L21–30) are **deliberately high-signal**: bare substrings like `"not found"`, `"unknown"`, or `"blocked"` are intentionally excluded to avoid silently skipping tests on genuine product failures (e.g., `"Session not found"`, `"MCP error unknown"`).

Detection operates on lowercased messages from multiple source shapes (strings, `Error` objects, plain objects with `message`/`error` fields), as the `start_debugging` tool result may be returned as a failure object or thrown.

---

### Key Symbols

#### `SPAWN_BLOCKED_SIGNATURES` (L21–30) — `readonly string[]` constant
A `const` tuple of lowercased substrings indicating environmental spawn failure:
- `'spawn unknown'` — Windows Smart App Control (SAC) blocks an unsigned binary
- `'spawn enoent'` — binary not found on PATH or at resolved path
- `'spawn eacces'` — binary present but not executable
- `'enoent'` — generic "no such file or directory"
- `'eacces'` — generic permission denied
- `'application control'` — SAC human-readable policy message
- `'not executable'`
- `'permission denied'`

#### `extractSpawnMessage(source: unknown): string` (L37–47)
Extracts and lowercases a message string from heterogeneous error sources:
- Returns `''` for falsy input
- Returns `source.toLowerCase()` for strings
- Returns `source.message.toLowerCase()` for `Error` instances
- For plain objects: returns `String(record.message ?? record.error ?? '').toLowerCase()`
- Returns `''` as fallback

#### `SkippableContext` interface (L61–64)
Minimal structural shape of the Vitest test context. Requires a `skip(note?: string): never` method, which **throws** to abort the test as skipped. Used to avoid coupling this utility to the full Vitest API.

#### `isAdapterSpawnBlocked(source: unknown): boolean` (L54–58)
Returns `true` if the extracted message matches any entry in `SPAWN_BLOCKED_SIGNATURES`. Delegates message extraction to `extractSpawnMessage`.

#### `skipIfSpawnBlocked(ctx, source, adapterName): boolean` (L78–92)
Primary consumer-facing function:
- If **not** spawn-blocked: returns `false` (caller proceeds normally)
- If spawn-blocked: calls `ctx.skip(note)` with a descriptive diagnostic message including `adapterName` and the extracted detail — **throws/never returns** in this branch
- **Warning:** Do not wrap in `try/catch` — skip is signalled via thrown exception (Vitest convention)

---

### Architectural Notes

- No runtime dependencies; pure logic operating on `unknown` inputs
- Designed for Vitest's test context API but only structurally coupled via `SkippableContext`
- All string matching is case-insensitive via `.toLowerCase()` at extraction time
- The `skipIfSpawnBlocked` return type is `boolean` but the `true` branch never returns (throws); this is a Vitest skip idiom
