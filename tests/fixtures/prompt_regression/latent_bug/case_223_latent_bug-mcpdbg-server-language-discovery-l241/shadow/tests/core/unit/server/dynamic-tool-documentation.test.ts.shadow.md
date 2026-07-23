# tests\core\unit\server\dynamic-tool-documentation.test.ts
@source-hash: 5b1591f38a1ed264
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:13Z


## Purpose
Unit tests verifying that `DebugMcpServer` tool documentation uses generic, portable path descriptions — not environment-specific paths (Windows absolute paths, Unix home dirs, container paths) — in its MCP tool schemas.

## Key Structure

### Module-Level Mocks (L5–50)
Two `vi.mock` calls establish a test environment:
- **`dependencies.js` mock (L5–31):** Stubs `createProductionDependencies` with a logger, fileSystem (existsSync always returns `true`), environment, networkManager, processManager, and commandFinder — all as `vi.fn()`.
- **`session-manager.js` mock (L33–50):** Stubs `SessionManager` constructor with all debug lifecycle methods (`startDebugging`, `setBreakpoint`, `getVariables`, `getStackTrace`, `getScopes`, `continue`, `stepOver`, `stepInto`, `stepOut`, `createSession`, `closeSession`, etc.).

### `getToolsFromServer` Helper (L56–105)
Core utility that extracts tool schemas from a live `DebugMcpServer` instance via introspection:
1. Intercepts `server.server.setRequestHandler` with a `vi.fn()` spy.
2. Calls the private `registerTools()` method (via unsafe cast at L82) to trigger re-registration.
3. Captures the handler registered for `ListToolsRequestSchema` (from `@modelcontextprotocol/sdk`).
4. Invokes that handler with a synthetic `tools/list` JSON-RPC request at L91.
5. Restores the original `setRequestHandler` at L94.
6. Returns `result.tools` typed as an array of schema objects with `name`, `description`, and `inputSchema`.

**Critical dependency:** Accesses `server.server` (public MCP server instance on `DebugMcpServer`) and calls the private `registerTools()` method — both must remain accessible.

### Test Suite: `Dynamic Tool Documentation` (L107–247)

#### `Hands-off Path Approach` (L110–215)
Six `it` blocks, each calling `getToolsFromServer(server)`:

| Test | Tool | Property | Assertion |
|---|---|---|---|
| L115 | `set_breakpoint` | `file.description` | Contains `'Path to the source file'`, `'absolute file paths'` |
| L128 | `start_debugging` | `scriptPath.description` | Contains `'Path to the script to debug'`, `'Use absolute paths or paths relative to your current working directory'` |
| L140 | `get_source_context` | `file.description` | Contains `'Path to the source file'`, `'Use absolute paths or paths relative to your current working directory'` |
| L152 | `set_breakpoint`, `start_debugging`, `get_source_context` | `file`/`scriptPath` | Must NOT match `C:\\`, `/home/`, `/workspace` regex patterns |
| L173 | `set_breakpoint`, `get_source_context` | `file.description` | Contains `'source file'`; `start_debugging.scriptPath.description` contains `'script'` |
| L188 | All three tools | respective path prop | Non-empty string; specific phrase checks per tool |

#### `MCP Response Serialization` (L217–247)
One `it` block verifying structural integrity: `tools` is a defined array, and path description properties for the three key tools are non-empty strings.

## Architectural Notes
- Uses `vi.mock` hoisting — mocks are registered before any import resolution, ensuring `DebugMcpServer` instantiation uses fakes throughout.
- The `getToolsFromServer` helper exploits the fact that `registerTools()` is idempotent (can be called multiple times) to re-capture handlers after setting up the spy.
- The test file imports `ListToolsRequestSchema` from the MCP SDK (L53) specifically for identity comparison (`schema === ListToolsRequestSchema`) in the spy at L74, ensuring the correct handler is captured.
- `server.server` at L70 assumes `DebugMcpServer` exposes its inner MCP `Server` instance as a public `server` field.
