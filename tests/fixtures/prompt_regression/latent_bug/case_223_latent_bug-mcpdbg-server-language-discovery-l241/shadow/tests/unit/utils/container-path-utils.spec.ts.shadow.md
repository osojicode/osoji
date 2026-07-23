# tests\unit\utils\container-path-utils.spec.ts
@source-hash: b3a6f7cff98ad93d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:49Z

## Unit Tests: `container-path-utils`

Tests for the `container-path-utils` utility module, covering all four exported functions: `isContainerMode`, `getWorkspaceRoot`, `resolvePathForRuntime`, and `getPathDescription`.

### Test Infrastructure

**`MockEnvironment` (L10–30)** — Implements `IEnvironment` from `@debugmcp/shared`. Accepts a `values` map and an optional `cwd` string (defaults to `'/app'`). Provides `get(key)`, `getAll()`, and `getCurrentWorkingDirectory()` methods. Used as a dependency-injected environment stand-in across all test suites.

---

### Test Suites

#### `isContainerMode` (L33–43)
- Returns `true` when `MCP_CONTAINER === 'true'` (L34–37)
- Returns `false` when `MCP_CONTAINER !== 'true'` (e.g., `'false'`) (L39–42)

#### `getWorkspaceRoot` (L45–63)
- Throws matching `/only be called in container mode/` when `MCP_CONTAINER` is not set (L46–48)
- Throws matching `/MCP_WORKSPACE_ROOT/` when container mode is active but `MCP_WORKSPACE_ROOT` env var is absent (L50–53)
- Strips trailing slash: `'/workspace/'` → `'/workspace'` (L55–62)

#### `resolvePathForRuntime` (L65–113)
Shared `containerEnv` fixture (L66–69): `MCP_CONTAINER=true`, `MCP_WORKSPACE_ROOT=/workspace`.
- Non-container mode: path returned unchanged (L71–75)
- Relative path in container mode: prefixed with workspace root, e.g. `'python/simple.py'` → `'/workspace/python/simple.py'` (L78–82)
- Idempotent: paths already starting with workspace root are not double-prefixed (L84–88)
- Path exactly equal to workspace root returned as-is (L90–93)
- Leading `/` stripped before joining to avoid double-slash: `'/examples/...'` → `'/workspace/examples/...'` (L96–100)
- Multiple leading slashes stripped: `'///examples/...'` → `'/workspace/examples/...'` (L102–106)
- Bare filename prefixed: `'script.py'` → `'/workspace/script.py'` (L108–112)

#### `getPathDescription` (L115–132)
- Non-container mode: returns `originalPath` unchanged (L116–119)
- Container mode but resolved path equals original: returns original (L121–124)
- Container mode with differing resolved path: returns `'<original>' (resolved to: '<resolved>')` (L126–131)

---

### Key Contracts Verified
- `MCP_CONTAINER` env var controls container mode detection
- `MCP_WORKSPACE_ROOT` env var provides the container workspace root
- `resolvePathForRuntime` normalizes all leading-slash variants to workspace-root-relative paths
- `getWorkspaceRoot` enforces preconditions with descriptive error messages
- `getPathDescription` generates human-readable path context only when paths diverge in container mode