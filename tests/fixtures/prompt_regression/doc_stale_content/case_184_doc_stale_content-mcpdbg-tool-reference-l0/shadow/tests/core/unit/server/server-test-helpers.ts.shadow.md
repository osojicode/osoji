# tests\core\unit\server\server-test-helpers.ts
@source-hash: 779cfb5f1295aeb8
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:30Z

## Purpose
Shared test helper factory functions for server unit tests. Provides reusable mock objects for dependency injection, MCP server instances, session managers, transports, and tool handler extraction.

## Key Exports

### `createMockDependencies()` (L8-71)
Returns a complete dependency injection bag for server construction under test:
- **logger**: delegated to `createMockLogger()` from test-utils
- **fileSystem** (L14-30): Full mock file-system adapter; `existsSync`/`pathExists`/`exists` default to `true`, `readFile` defaults to `'{}'`, `readdir` defaults to `[]`, `stat` returns `{ isFile: () => true }`
- **processManager / networkManager / proxyProcessLauncher / proxyManagerFactory / sessionStoreFactory** (L31-35): bare `vi.fn()` stubs
- **environment** (L36-40): delegates `get` to `process.env`, `getAll` to spread of `process.env`, `getCurrentWorkingDirectory` to `process.cwd()`
- **pathUtils** (L41-68): Cross-platform path mock; `isAbsolute` performs real platform check (win32 vs POSIX), `resolve` joins with `/` and collapses duplicates, `join` naive-joins with `/`, `dirname`/`basename` use `lastIndexOf('/')`, `sep` hardcoded to `'/'`
- **adapterRegistry**: delegated to `createMockAdapterRegistry()`

### `createMockServer()` (L73-80)
Minimal MCP server stub with `setRequestHandler`, `connect`, `close` (all `vi.fn()`), and `onerror: undefined`.

### `createMockSessionManager(mockAdapterRegistry)` (L82-108)
Full debug session manager mock. All methods are `vi.fn()`. Notable defaults:
- `getSessionPolicy` returns `{}` (L99)
- `getAdapterRegistry` returns the passed-in `mockAdapterRegistry` (L105)
- `adapterRegistry` property directly exposes `mockAdapterRegistry` (L106)

### `createMockStdioTransport()` (L110-112)
Returns an empty object `{}` — placeholder stub.

### `getToolHandlers(mockServer)` (L114-120)
Extracts registered MCP tool handlers from a mock server's `setRequestHandler` call history:
- `listToolsHandler`: first registered handler (`calls[0][1]`) — assumed to be `ListToolsRequestSchema` handler
- `callToolHandler`: second registered handler (`calls[1][1]`) — assumed to be `CallToolRequestSchema` handler
- Returns `undefined` for either if server hasn't had enough handlers registered yet.

## Dependencies
- `vitest` `vi` — mock creation
- `createMockLogger` from `test-utils/helpers/test-dependencies` — logger mock factory
- `createMockAdapterRegistry` from `test-utils/mocks/mock-adapter-registry` — adapter registry mock factory

## Architectural Notes
- All helpers follow a factory pattern (no shared state between tests).
- `pathUtils.isAbsolute` contains genuine platform branching logic (L44-48), making it more realistic than a naive stub.
- `pathUtils.resolve` (L50-53) does NOT replicate true `path.resolve` semantics (no CWD resolution, just string concatenation); tests relying on absolute-path resolution may behave differently from production.
- Handler index assumptions in `getToolHandlers` (L117-118) are fragile — they depend on registration order in the server under test.