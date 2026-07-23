# tests\test-utils\helpers\adapter-spawn.ts
@source-hash: 3989efeaf1ee95aa
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:44Z

## Purpose

Provides detection and Vitest test-skip logic for environmental adapter spawn failures in e2e smoke tests. When a debug adapter binary (e.g., CodeLLDB's `codelldb.exe`, Delve's `dlv`) fails to spawn due to missing binary, permissions, or OS policy (e.g., Windows Smart App Control), tests should skip gracefully rather than hard-fail with cryptic errors.

## Key Exports

### `SPAWN_BLOCKED_SIGNATURES` (L21–30)
A `readonly` tuple of **lowercased** signature strings used to detect environmental spawn failures:
- `'spawn unknown'` — Windows SAC blocking unsigned binary
- `'spawn enoent'` — adapter binary not found
- `'spawn eacces'` — adapter binary not executable
- `'enoent'` — generic no-such-file error
- `'eacces'` — generic permission denied
- `'application control'` — SAC human-readable policy message
- `'not executable'`
- `'permission denied'`

Intentionally **high-signal**: bare substrings like `"not found"`, `"unknown"`, `"blocked"` are excluded to avoid false positives on messages like "Session not found" or "MCP error unknown".

### `extractSpawnMessage(source: unknown): string` (L37–47)
Normalizes diverse error sources into a lowercase string for signature matching:
- `null`/`undefined`/falsy → `''`
- `string` → lowercased directly
- `Error` instance → `source.message.toLowerCase()`
- Plain object → checks `record.message ?? record.error ?? ''` (handles both tool result failure objects and thrown errors)
- Fallback → `''`

### `isAdapterSpawnBlocked(source: unknown): boolean` (L54–58)
Returns `true` if the lowercased message from `extractSpawnMessage` contains any signature from `SPAWN_BLOCKED_SIGNATURES`. Used as the detection predicate before deciding to skip a test.

### `SkippableContext` interface (L61–64)
Minimal structural typing for Vitest's test context. Requires `skip(note?: string): never`. The `never` return type is intentional — `ctx.skip()` throws to abort the test.

### `skipIfSpawnBlocked(ctx, source, adapterName): boolean` (L78–92)
Main entry point for e2e smoke tests:
1. Calls `isAdapterSpawnBlocked(source)` — if false, returns `false` and test proceeds normally.
2. If spawn-blocked: calls `ctx.skip(...)` with a human-readable diagnostic including `adapterName` and the extracted detail message. **This throws and never returns** (via Vitest's `ctx.skip()` mechanism).
- **Critical usage constraint**: Must NOT be wrapped in `try/catch` or the skip will be swallowed.

## Architectural Notes
- All signature matching is case-insensitive (messages are lowercased before comparison).
- The `SkippableContext` interface is structurally compatible with Vitest's test context, enabling use without importing Vitest types directly.
- The `skipIfSpawnBlocked` return type is declared `boolean` but in the blocked branch it actually `never` returns (throws). Callers can safely check `if (skipIfSpawnBlocked(...)) { ... }` pattern, but the `true` branch is unreachable — `false` is the only actual return value.