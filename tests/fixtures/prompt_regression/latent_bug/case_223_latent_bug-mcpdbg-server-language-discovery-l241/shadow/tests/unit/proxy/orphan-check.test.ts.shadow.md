# tests\unit\proxy\orphan-check.test.ts
@source-hash: 1eea348a6b8eb18c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:33Z

## Unit Tests: `orphan-check` utility

Tests for `shouldExitAsOrphan` and `shouldExitAsOrphanFromEnv` from `src/proxy/utils/orphan-check.ts`.

### Test Structure

**`shouldExitAsOrphan` (L5–17):** Pure-logic tests with explicit `(ppid, isContainer)` arguments.
- `(1, false)` → `true`: exits when parent is PID 1 (init) and NOT in a container (L7)
- `(1, true)` → `false`: does NOT exit when PID 1 but inside a container (L11)
- `(42, false)` → `false`: does NOT exit when parent is not init process (L15)

**`shouldExitAsOrphanFromEnv` (L19–33):** Tests env-var-to-boolean derivation layer.
- `MCP_CONTAINER: 'true'` + ppid 1 → `false`: container flag suppresses orphan exit (L22–23)
- `MCP_CONTAINER: 'false'` + ppid 1 → `true`: non-container flag allows orphan exit (L25–26)
- No env arg → falls back to `process.env`; uses `vi.stubEnv('MCP_CONTAINER', 'true')` to simulate (L30–31)

### Key Behavioral Contracts Verified
- Orphan detection triggers only when `ppid === 1` AND `isContainer === false`
- `MCP_CONTAINER` env var controls container mode; any value other than `'true'` (e.g., `'false'`) is treated as non-container
- `shouldExitAsOrphanFromEnv` defaults to `process.env` when second argument is omitted

### Dependencies
- **vitest**: `describe`, `it`, `expect`, `vi` — `vi.stubEnv` used for env variable stubbing (L1, L30)
- **SUT**: `shouldExitAsOrphan`, `shouldExitAsOrphanFromEnv` from `../../../src/proxy/utils/orphan-check.js` (L2)