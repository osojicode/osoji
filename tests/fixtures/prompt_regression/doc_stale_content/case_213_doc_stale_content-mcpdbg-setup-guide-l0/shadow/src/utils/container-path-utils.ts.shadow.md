# src\utils\container-path-utils.ts
@source-hash: b82e9e64838bb7e8
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:16Z

## Container Path Utilities (src/utils/container-path-utils.ts)

Centralized path resolution logic for dual-mode (host/container) deployment. Determines runtime mode via environment variables and transforms paths accordingly.

### Architecture & Policy
- **Single source of truth** for all path resolution (host vs. container mode)
- **Container mode** requires `MCP_CONTAINER=true` AND `MCP_WORKSPACE_ROOT` env vars
- **Host mode** is a transparent pass-through (no transformation)
- **No OS-specific heuristics** — deterministic behavior only
- All functions accept `IEnvironment` (from `@debugmcp/shared`) for testability/DI

### Key Functions

#### `isContainerMode` (L17-19)
Checks `MCP_CONTAINER === 'true'` via `environment.get(...)`. Pure predicate used by all other functions.

#### `getWorkspaceRoot` (L25-40)
- **Guard**: throws if called outside container mode (L27)
- **Guard**: throws with descriptive message if `MCP_WORKSPACE_ROOT` is unset (L32-36)
- **Normalizes** trailing slashes from the root path (L39)
- Example expected value: `/workspace`

#### `resolvePathForRuntime` (L52-69)
Primary path resolution entry point:
- Host mode → returns `inputPath` unchanged (L54-56)
- Container mode, path already under workspace root → idempotent, returns as-is (L62-64)
- Container mode, other paths → strips leading slashes then prepends `workspaceRoot/` (L67-68)

#### `getPathDescription` (L75-89)
Produces human-readable path description for error messages:
- Host mode or `originalPath === resolvedPath` → returns `originalPath`
- Otherwise → returns `'<original>' (resolved to: '<resolved>')` format

### Dependencies
- `IEnvironment` from `@debugmcp/shared` — interface with `.get(key: string): string | undefined` method used for environment variable access

### Critical Invariants
- `getWorkspaceRoot` must only be called when `isContainerMode` is true; callers in this file enforce this
- `resolvePathForRuntime` handles all path cases: already-resolved absolute paths, paths with leading slashes, and bare relative paths
- Trailing-slash normalization on `workspaceRoot` prevents double-slash in constructed paths