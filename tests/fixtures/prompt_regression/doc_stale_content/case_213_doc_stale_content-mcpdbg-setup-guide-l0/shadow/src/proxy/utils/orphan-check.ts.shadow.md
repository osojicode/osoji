# src\proxy\utils\orphan-check.ts
@source-hash: 25d1a00cf87a291a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:20Z

## Orphan Exit Decision Helper (`src/proxy/utils/orphan-check.ts`)

### Purpose
Determines whether the proxy process should exit as an "orphan" based on parent PID and container environment context. Handles the edge case where `PPID=1` is normal inside containers (PID namespaces) and should NOT trigger orphan exit.

### Key Functions

#### `shouldExitAsOrphan` (L11–14) — Core Logic
- **Signature:** `(ppid: number, inContainer: boolean) => boolean`
- Returns `true` only when `ppid === 1` AND `inContainer` is `false`.
- In container environments, `PPID=1` is expected behavior; this function suppresses false-positive orphan detection.

#### `shouldExitAsOrphanFromEnv` (L19–25) — Env-aware Convenience Wrapper
- **Signature:** `(ppid: number, env?: NodeJS.ProcessEnv) => boolean`
- Defaults `env` to `process.env` if not provided.
- Reads `env.MCP_CONTAINER === 'true'` (L23) to determine container status, then delegates to `shouldExitAsOrphan`.
- Typical call site passes `process.ppid` as `ppid`.

### Environment Variable Contract
- **`MCP_CONTAINER`**: Must be set to the string `'true'` to suppress orphan exit in container environments. Any other value (including `'1'`, `'yes'`, absent) is treated as non-container.

### Architectural Notes
- Pure utility module — no side effects, no imports, no state.
- Two-layer design: pure logic function (`shouldExitAsOrphan`) + env-reading wrapper (`shouldExitAsOrphanFromEnv`) allows easy unit testing of the core logic without environment mocking.
- Intended to be called by the proxy process lifecycle/watchdog logic on parent PID change events.