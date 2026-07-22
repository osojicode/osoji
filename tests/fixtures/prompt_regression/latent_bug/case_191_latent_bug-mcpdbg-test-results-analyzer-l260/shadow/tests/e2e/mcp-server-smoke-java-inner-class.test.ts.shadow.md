# tests\e2e\mcp-server-smoke-java-inner-class.test.ts
@source-hash: f294bc67bcb8ab56
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:59Z

## Java Inner Class Breakpoint Smoke Test (E2E)

End-to-end smoke test verifying that the MCP debug server correctly handles breakpoints inside non-static Java inner classes via the MCP protocol. Tests the JDI bridge's `ClassPrepareRequest` with `"$*"` suffix and `"$"`-stripping in `handleClassPrepared`.

### Test Target
- Java source: `InnerClassTest.java` — has a non-static inner class `Inner` with `compute(int, int)` method
- Breakpoint target: line 15 (`int result = a + b;` inside `Inner.compute()`)
- Expected local variables at breakpoint: `a=7`, `b=8`

### Structure

**Module-level constants (L27-29):**
- `__filename`, `__dirname`, `ROOT` — resolve project root for locating `dist/index.js`

**`waitForPausedState` (L34-48):** Polls `get_stack_trace` tool up to `maxAttempts` (default 20) times at `intervalMs` (default 500ms) intervals. Returns stack frames object when non-empty frames are found, or `null` on timeout. Used to detect breakpoint hits asynchronously.

**`describe` block (L50-213): `'MCP Server Java Inner Class Breakpoint Smoke Test @requires-java'`**

Suite-level state:
- `mcpClient: Client | null` — MCP SDK client
- `transport: StdioClientTransport | null` — stdio transport to MCP server
- `sessionId: string | null` — active debug session ID for cleanup

**`beforeAll` (L55-85):**
1. Checks JDK availability via `execSync('java -version')` and `execSync('javac -version')` — skips setup silently if not found
2. Spawns MCP server via `StdioClientTransport` pointing to `dist/index.js` with `--log-level info`
3. Creates `Client` named `'java-inner-class-test-client'`
4. Connects client to transport; timeout 30s

**`afterAll` (L87-104):**
- Closes active debug session if present
- Closes MCP client and transport

**`afterEach` (L106-115):**
- Closes and nullifies `sessionId` after each test to prevent session leaks

**Primary test: `'should hit a breakpoint inside a non-static inner class'` (L117-213), timeout 60s:**
1. Re-checks JDK availability (returns early if missing — graceful skip pattern)
2. Calls `prepareJavaExample('InnerClassTest')` to compile source and get `sourcePath`, `classDir`, `mainClass` (L127)
3. Creates debug session via `create_debug_session` tool; asserts `sessionId` defined (L131-138)
4. Sets breakpoint at line 15 via `set_breakpoint` tool; asserts `success: true` (L141-146)
5. Starts debugging via `start_debugging` with `dapLaunchArgs: { mainClass, classpath, cwd, stopOnEntry: false }` (L149-164)
6. Polls for paused state with `waitForPausedState(mcpClient!, sessionId, 30, 500)` — 30 attempts × 500ms = up to 15s (L168)
7. **Hard assertions:**
   - `stackResponse` not null
   - `frames.length > 0`
   - `topFrame.name` contains `'compute'` (case-insensitive)
   - `topFrame.line === 15` (if numeric and positive)
8. Fetches local variables via `get_local_variables` tool (L186-200)
9. **Hard assertions:** `a === '7'`, `b === '8'`
10. Continues execution via `continue_execution` tool; asserts `success: true` (L209-210)

### Key Patterns
- **Graceful JDK skip:** JDK check duplicated in both `beforeAll` and the test body (L57-63, L119-125) — test returns early rather than using `skip()`, preventing assertion failures when JDK is absent
- **`callToolSafely` wrapper:** Used for `get_stack_trace`, `close_debug_session`, `continue_execution` (error-tolerant); direct `mcpClient!.callTool` used for session-critical calls
- **`parseSdkToolResult`:** Unwraps MCP SDK tool results into plain objects for assertion
- **Non-null assertion `!`:** Used on `mcpClient` and `sessionId` after guards confirm non-null

### Dependencies
- `@modelcontextprotocol/sdk` — `Client`, `StdioClientTransport`
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils.js` — `prepareJavaExample` (compiles Java source, returns paths)
- MCP server binary: `dist/index.js` at project root
- JDK (`java`, `javac`) on PATH
