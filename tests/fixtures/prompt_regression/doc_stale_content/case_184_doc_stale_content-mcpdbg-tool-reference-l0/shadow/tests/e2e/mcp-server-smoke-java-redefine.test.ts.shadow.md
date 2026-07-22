# tests\e2e\mcp-server-smoke-java-redefine.test.ts
@source-hash: 8794bd4d13aafb7e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:44Z

## Java Hot-Reload (redefine_classes) E2E Smoke Test

End-to-end smoke test that validates the MCP `redefine_classes` tool for Java class hot-swapping via JDWP. Exercises the full lifecycle: JDK availability check → compile → JVM spawn with JDWP → MCP session attach → breakpoint → eval before swap → recompile V2 → hot-swap → eval after swap → verify behavior change.

### File Constants (L25-27)
- `__filename`, `__dirname`: ESM-compatible path resolution via `fileURLToPath`
- `ROOT`: resolved to repo root (`../..` from `__dirname`)

### Key Helpers

**`getFreePort()` (L29-43)**
- Binds a TCP server to port 0 on 127.0.0.1, captures the OS-assigned port, closes the server, resolves with the port number
- Returns `Promise<number>`

**`waitForPausedState()` (L45-63)**
- Polls `get_stack_trace` MCP tool up to `maxAttempts` times (default 20) with `intervalMs` delay (default 500ms)
- Optional `validate` callback filters which pause state is acceptable (used to verify frame file/name/line)
- Returns the result object with `stackFrames` if paused, or `null` on timeout
- Parameters: `client`, `sessionId`, `maxAttempts=20`, `intervalMs=500`, `validate?`

### Test Suite: `describe` block (L65-288)
Suite tag: `@requires-java` (in describe label — for external test runner filtering)

**Suite-level variables (L66-69):**
- `mcpClient: Client | null` — MCP SDK client
- `transport: StdioClientTransport | null` — stdio transport to MCP server process
- `sessionId: string | null` — debug session ID
- `jvmProcess: ChildProcess | null` — spawned JVM process

**Java source paths (L71-73):**
- `testJavaDir`: `examples/java/` under ROOT
- `mainFile`: `RedefineTarget.java`
- `v2File`: `RedefineTargetV2.java`

**`beforeAll` (L75-88):**  Starts MCP server as a child process (`dist/index.js --log-level info`) via `StdioClientTransport`, creates MCP `Client` named `java-redefine-test`, connects. Timeout: 30s.

**`afterAll` (L90-97):** Closes debug session (best-effort), closes MCP client and transport, kills JVM with SIGKILL if alive.

**`afterEach` (L99-108):** Closes debug session (best-effort), nulls `sessionId`, kills JVM with SIGKILL, nulls `jvmProcess`. Ensures isolation between tests.

### Main Test: `should hot-swap a class...` (L110-287), timeout 90s

**Step-by-step flow:**
1. **JDK check (L112-118):** `execSync('java -version')` + `execSync('javac -version')` — skips gracefully if unavailable
2. **Compile V1 (L121-124):** `javac -g -d <testJavaDir> <mainFile>` — produces `RedefineTarget.class` with `getValue()` returning 42
3. **Spawn JVM with JDWP (L129-139):** `java -agentlib:jdwp=transport=dt_socket,server=y,address=<port>,suspend=y -cp <testJavaDir> RedefineTarget` — suspends on start
4. **Wait for JDWP ready (L142-161):** Watches stdout/stderr for `"Listening for transport"` with 15s timeout
5. **Create MCP debug session (L166-171):** Calls `create_debug_session` with `language: 'java'`
6. **Set breakpoint (L175-179):** `set_breakpoint` at `mainFile:19`
7. **Attach to JVM (L183-192):** `attach_to_process` with `port`, `host: '127.0.0.1'`, `sourcePaths`
8. **Continue past initial suspend (L196-200):** `continue_execution`
9. **Wait for breakpoint at line 19 (L204-206):** Uses `waitForPausedState` with 30 attempts × 500ms
10. **Evaluate before hot-swap (L210-216):** `evaluate_expression` with `'getValue()'` — expects result `'42'`
11. **Recompile with V2 (L220-232):** Reads `RedefineTargetV2.java`, overwrites `mainFile`, compiles, then **restores original source** in `finally` block
12. **Call `redefine_classes` (L236-250):** `classesDir: testJavaDir`, `sinceTimestamp: 0` — expects `success: true`, `redefinedCount >= 1`, and `RedefineTarget` in `redefined` list
13. **Evaluate after hot-swap (L256-262):** `evaluate_expression` with `'getValue()'` — expects result `'99'`
14. **Continue to finish (L265-269):** `continue_execution`
15. **Cleanup (L274-285):** Deletes `RedefineTarget.class`, kills JVM

### MCP Tool Names Used
- `create_debug_session`
- `set_breakpoint`
- `attach_to_process`
- `continue_execution`
- `get_stack_trace`
- `evaluate_expression`
- `redefine_classes`
- `close_debug_session`

### Dependencies
- `@modelcontextprotocol/sdk` — `Client`, `StdioClientTransport`
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely`
- Node built-ins: `path`, `net`, `url`, `child_process`, `fs`
- External: JDK (`java`, `javac` on PATH)
- Java source fixtures: `examples/java/RedefineTarget.java`, `examples/java/RedefineTargetV2.java`
- MCP server binary: `dist/index.js`

### Architectural Notes
- Uses `sinceTimestamp: 0` for `redefine_classes` to force inclusion of all `.class` files regardless of mtime — appropriate since the class is freshly compiled mid-test
- Source file is temporarily overwritten with V2 content and immediately restored in a `finally` block (L229-232) to avoid polluting the repo
- JVM is spawned with `suspend=y` so the debugger can set breakpoints before execution starts
- `parseSdkToolResult` (from utils) unwraps MCP SDK response envelopes; `callToolSafely` wraps tool calls with error handling
