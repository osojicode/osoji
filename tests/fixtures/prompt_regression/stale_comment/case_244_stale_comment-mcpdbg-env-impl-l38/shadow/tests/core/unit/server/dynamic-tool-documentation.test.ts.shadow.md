# tests\core\unit\server\dynamic-tool-documentation.test.ts
@source-hash: 5b1591f38a1ed264
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:13Z

## Purpose
Unit tests verifying that `DebugMcpServer`'s tool documentation uses generic, environment-agnostic path guidance — not hardcoded working directories or container-specific paths.

## Key Elements

### Module-Level Mocks (L5-51)
Two vi.mock calls set up test isolation:
- **`dependencies.js` mock (L5-31):** Stubs `createProductionDependencies` to return a minimal fake dependency graph with no-op logger, fileSystem, environment, networkManager, processManager, and commandFinder.
- **`session-manager.js` mock (L33-50):** Stubs `SessionManager` constructor to return an object with all debug operation methods as `vi.fn()`, `getAllSessions` returning `[]`.

### Helper: `getToolsFromServer` (L56-105)
Introspects a live `DebugMcpServer` instance to extract registered tool definitions without access to private methods:
1. Monkey-patches `server.server.setRequestHandler` with a spy that intercepts the handler registered for `ListToolsRequestSchema`.
2. Force-calls the private `registerTools()` method via type-cast (`server as unknown as { registerTools(): void }`).
3. Invokes the captured handler with a minimal JSON-RPC 2.0 `tools/list` request.
4. Restores the original `setRequestHandler`.
5. Returns the typed tools array.
- **Critical assumption:** `registerTools()` is a private method on `DebugMcpServer` and `server.server` exposes `setRequestHandler` publicly.

### Test Suite: `Dynamic Tool Documentation` (L107-247)

#### `Hands-off Path Approach` (L110-215)
Each test calls `getToolsFromServer` and inspects tool `inputSchema.properties` descriptions:

| Test | Tool | Property | Assertion |
|------|------|----------|-----------|
| L115-126 | `set_breakpoint` | `file` | Contains "Path to the source file", "absolute file paths" |
| L128-138 | `start_debugging` | `scriptPath` | Contains "Path to the script to debug", "Use absolute paths or paths relative to your current working directory" |
| L140-150 | `get_source_context` | `file` | Contains "Path to the source file", "Use absolute paths or paths relative to your current working directory" |
| L152-171 | All three tools | `file`/`scriptPath` | Does NOT match `C:\`, `/home/`, `/workspace` (no environment-specific paths) |
| L173-186 | `set_breakpoint`/`get_source_context` | `file` | Contains "source file"; `start_debugging.scriptPath` contains "script" |
| L188-214 | All three | varies | Non-empty string; tool-specific content verified |

#### `MCP Response Serialization` (L217-247)
Verifies that the tools list response structure is a proper array and that each path-relevant tool property description is a non-empty string — confirming proper MCP protocol serialization.

## Dependencies
- **`DebugMcpServer`** from `../../../../src/server.js` — the production class under test; accessed via `server.server.setRequestHandler` (inner MCP server handle) and private `registerTools()`.
- **`ListToolsRequestSchema`** from `@modelcontextprotocol/sdk/types.js` — used as the discriminant to identify the correct request handler during spy interception (L74).

## Architecture Notes
- Tests use introspection via private method casting rather than dependency injection, which makes them sensitive to `DebugMcpServer` internal structure changes.
- `beforeEach` creates a fresh `DebugMcpServer()` instance for each test group (L112, L219), ensuring no state leakage.
- The `getToolsFromServer` helper mutates `server.server.setRequestHandler` in-place and restores it, so concurrent test execution could cause flakiness.
- No actual debugger/DAP protocol connections are made; all networking dependencies are fully mocked.