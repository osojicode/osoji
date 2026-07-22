# tests\e2e\mcp-server-smoke-java.test.ts
@source-hash: 103d5c4dffabae01
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:41Z

## Java MCP Server Smoke Tests (E2E, Launch Mode)

End-to-end smoke tests for Java debugging via the MCP (Model Context Protocol) interface, exercising the full debug lifecycle using a real MCP server process (spawned via stdio transport) and a real JDK.

### Test Suite Structure

**`describe` block: `MCP Server Java Debugging Smoke Test @requires-java` (L56–456)**

Shared state:
- `mcpClient: Client | null` (L57) — MCP SDK client instance
- `transport: StdioClientTransport | null` (L58) — stdio transport to MCP server subprocess
- `sessionId: string | null` (L59) — tracks active debug session for cleanup

### Lifecycle Hooks

- **`beforeAll` (L61–82):** Spawns MCP server via `process.execPath dist/index.js --log-level info` with `NODE_ENV=test`. Connects MCP client over stdio. Timeout: 30s.
- **`afterAll` (L84–101):** Closes active debug session (if any), closes MCP client, closes transport.
- **`afterEach` (L103–112):** Closes active debug session and resets `sessionId` to null after each test.

### Helper Function

**`waitForPausedState` (L40–54):** Polls `get_stack_trace` MCP tool up to `maxAttempts` (default 20) times at `intervalMs` (default 500ms) intervals until stack frames are non-empty, indicating a breakpoint hit. Returns the stack response or `null` on timeout.

### Test Cases

1. **`should create Java debug session through MCP interface` (L114–130)**
   - Calls `create_debug_session` with `language: 'java'`
   - Asserts `sessionId` is defined and truthy
   - No JDK required

2. **`should complete Java debugging flow with verified stack and variables` (L132–253, timeout 60s)**
   - Guards with `execSync('java -version')` / `execSync('javac -version')` — skips gracefully if JDK absent
   - Uses `prepareJavaExample('HelloWorld')` to get `{sourcePath, classDir, mainClass}`
   - Full flow: create session → set breakpoint (line 10, `add()`) → `start_debugging` with `dapLaunchArgs {mainClass, classpath, cwd, stopOnEntry: false}` → poll for pause → assert top frame is `add()` at line 10 → get local variables, assert `a='10'` and `b='20'` → `step_over` → `continue_execution`

3. **`should hit a breakpoint added while the application is paused` (L255–368, timeout 60s)**
   - Guards with JDK check; uses `prepareJavaExample('HelloWorld')`
   - Flow: set BP at line 10 (add) → start → wait for first BP → while paused, set second BP at line 15 (greet) → continue → wait for second BP at `greet():15` → assert `name == '"World"'` → continue to finish

4. **`should support conditional breakpoints` (L370–455, timeout 60s)**
   - Guards with JDK check; uses `prepareJavaExample('HelloWorld')`
   - Sets breakpoint at line 10 with `condition: 'a > 5'` (satisfied since `a=10`)
   - Asserts breakpoint fires, `a='10'` in locals, then continues to finish

### MCP Tool Names Used
- `create_debug_session` — `{language, name}`
- `set_breakpoint` — `{sessionId, file, line, condition?}`
- `start_debugging` — `{sessionId, scriptPath, args, dapLaunchArgs: {mainClass, classpath, cwd, stopOnEntry}}`
- `get_stack_trace` — `{sessionId}`
- `get_local_variables` — `{sessionId}`
- `step_over` — `{sessionId}`
- `continue_execution` — `{sessionId}`
- `close_debug_session` — `{sessionId}`

### Key Dependencies
- `smoke-test-utils.js`: `parseSdkToolResult` (parses MCP SDK tool call results), `callToolSafely` (safe wrapper for tool calls)
- `java-example-utils.js`: `prepareJavaExample` (compiles Java source, returns `{sourcePath, classDir, mainClass}`)
- `@modelcontextprotocol/sdk`: `Client`, `StdioClientTransport`
- MCP server binary: `dist/index.js` (relative to repo root `ROOT = __dirname/../..`)

### Architectural Patterns
- All JDK-dependent tests use `try { execSync(...) } catch { return; }` for graceful skip (no `test.skip`)
- Session cleanup is handled in both `afterEach` (per-test) and `afterAll` (suite-level failsafe)
- Non-null assertion (`mcpClient!`) used throughout tests since `beforeAll` guarantees initialization
- `waitForPausedState` abstracts the async polling pattern needed because JDI breakpoint events are asynchronous
- `dapLaunchArgs` passed directly to the MCP tool to configure JDI launch parameters
