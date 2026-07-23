# tests\core\unit\server\server-test-helpers.ts
@source-hash: 779cfb5f1295aeb8
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:41Z

## Purpose
Shared test helper factory functions for server unit tests. Provides consistent mock objects for dependencies, MCP server, session manager, stdio transport, and tool handler extraction.

## Key Exports

### `createMockDependencies()` (L8-71)
Factory returning a complete dependency injection object for server tests. Contains:
- **`logger`**: delegated to `createMockLogger()` from test-utils
- **`fileSystem`** (L14-30): Full mock filesystem with all methods; defaults are permissive (`existsSync → true`, `readFile → '{}'`, `stat → {isFile: () => true}`, `readdir → []`)
- **`processManager`, `networkManager`, `proxyProcessLauncher`, `proxyManagerFactory`, `sessionStoreFactory`** (L31-35): Bare `vi.fn()` stubs
- **`environment`** (L36-40): Delegates `get` to `process.env[key]`, `getAll` to spread of `process.env`, `getCurrentWorkingDirectory` to `process.cwd()`
- **`pathUtils`** (L41-68): Platform-aware `isAbsolute` (detects Win32 drive letters and UNC paths at L44-48), simple `/`-joining `resolve`, `join`, `dirname`, `basename` with optional extension stripping; `sep` hardcoded to `'/'`
- **`adapterRegistry`**: delegated to `createMockAdapterRegistry()`

### `createMockServer()` (L73-80)
Returns a minimal MCP server stub with `setRequestHandler`, `connect`, `close` as `vi.fn()`, and `onerror` initialized to `undefined`.

### `createMockSessionManager(mockAdapterRegistry)` (L82-108)
Returns a comprehensive session manager stub. All debug lifecycle methods are bare `vi.fn()`. Notable pre-configured mocks:
- `getSessionPolicy` → `{}` (L99)
- `getAdapterRegistry` → `mockAdapterRegistry` (L105)
- `adapterRegistry` field also set to `mockAdapterRegistry` (L106)

### `createMockStdioTransport()` (L110-112)
Returns an empty object `{}` as a transport stub.

### `getToolHandlers(mockServer)` (L114-119)
Extracts registered MCP tool handlers from `mockServer.setRequestHandler.mock.calls`:
- `listToolsHandler`: first registered handler (index 0, slot 1) — assumed to be `ListToolsRequestSchema` handler
- `callToolHandler`: second registered handler (index 1, slot 1) — assumed to be `CallToolRequestSchema` handler
Returns object with both (potentially `undefined` if not yet registered).

## Architecture Notes
- All factories use Vitest's `vi.fn()` for spy capability
- `pathUtils.resolve` mock (L52) uses simple join+dedup of slashes — does NOT correctly handle absolute paths or path normalization edge cases
- `pathUtils.sep` is hardcoded to `'/'` (L67), inconsistent with `isAbsolute` which handles Windows paths — could cause cross-platform test issues
- `getToolHandlers` relies on registration order convention: tests must register ListTools before CallTool

## Dependencies
- `vitest.vi` — mock/spy infrastructure
- `createMockLogger` from `test-utils/helpers/test-dependencies`
- `createMockAdapterRegistry` from `test-utils/mocks/mock-adapter-registry`