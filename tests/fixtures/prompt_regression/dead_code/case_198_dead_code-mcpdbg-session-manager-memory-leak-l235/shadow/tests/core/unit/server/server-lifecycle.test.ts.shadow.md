# tests\core\unit\server\server-lifecycle.test.ts
@source-hash: d0d93d0c50b87d86
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:45Z

## Server Lifecycle Tests

Unit tests for `DebugMcpServer` lifecycle operations (start/stop), covering stdio transport initialization, session manager teardown, and error propagation during shutdown.

### Test Structure

**Suite:** `Server Lifecycle Tests` (L23–82)

All external dependencies are fully mocked via `vi.mock` (L18–21), and mock instances are wired up via `vi.mocked(...).mockImplementation` in `beforeEach` (L29–41).

---

### Setup / Teardown

**`beforeEach` (L29–41):**
- Creates `mockDependencies` via `createMockDependencies()` and stubs `createProductionDependencies` to return it.
- Creates `mockServer` via `createMockServer()` and stubs `Server` constructor to return it.
- Creates `mockStdioTransport` via `createMockStdioTransport()` and stubs `StdioServerTransport` constructor to return it.
- Creates `mockSessionManager` via `createMockSessionManager(mockDependencies.adapterRegistry)` and stubs `SessionManager` constructor to return it.

**`afterEach` (L43–45):** Clears all mocks via `vi.clearAllMocks()`.

---

### Test Cases

#### `Server Start` (L47–55)
- **`should start server with stdio transport` (L48–54):** Instantiates `DebugMcpServer`, calls `start()`, and asserts that `logger.info` was called with a string containing `'[MCP Server] Started at'`.

#### `Server Stop` (L57–81)
- **`should stop server and close all sessions` (L58–66):** Instantiates `DebugMcpServer`, stubs `closeAllSessions` to resolve, calls `stop()`, and asserts both `closeAllSessions` was called and `logger.info` was called with `'Debug MCP Server stopped'`.
- **`should handle errors when closing sessions during stop` (L68–79):** Stubs `closeAllSessions` to reject with an error, calls `stop()` inside a try/catch (intentionally swallowing propagated errors), and asserts only that `closeAllSessions` was called — does not assert error suppression or re-throw behavior.

---

### Key Dependencies (mocked)
| Module | Mock target |
|---|---|
| `@modelcontextprotocol/sdk/server/index.js` | `Server` class constructor |
| `@modelcontextprotocol/sdk/server/stdio.js` | `StdioServerTransport` constructor |
| `../../../../src/session/session-manager.js` | `SessionManager` constructor |
| `../../../../src/container/dependencies.js` | `createProductionDependencies` |

Mock helpers imported from `./server-test-helpers.js` (L11–15): `createMockDependencies`, `createMockServer`, `createMockSessionManager`, `createMockStdioTransport`.

---

### Notable Patterns & Constraints
- The error-handling test (L68–79) uses a broad try/catch and only asserts `closeAllSessions` was called — it does **not** assert whether `stop()` re-throws or swallows the error. This is intentional per the inline comment (L75).
- `mockStdioTransport` is created but not directly asserted against in the start test; the test relies solely on logger output.
- `debugServer` is re-instantiated in each `it` block rather than in `beforeEach`, so constructor side-effects are tested per case.