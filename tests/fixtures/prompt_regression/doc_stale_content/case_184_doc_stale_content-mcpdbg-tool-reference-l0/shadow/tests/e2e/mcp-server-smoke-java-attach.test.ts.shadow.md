# tests\e2e\mcp-server-smoke-java-attach.test.ts
@source-hash: 1bfde5a0f1807b18
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:54Z

## Java Attach-Mode Smoke Tests via MCP Interface

End-to-end test suite verifying Java JDWP attach-mode debugging through the MCP server interface. Spawns a real JVM with JDWP agent (`suspend=y`), then uses MCP tool calls to attach a debugger, set/hit breakpoints, and inspect local variables.

### File Structure

- **Module-level constants** (L36–38): `__filename`, `__dirname`, `ROOT` — resolve project root two levels up from test file.
- **`getFreePort()` (L43–57)**: Finds an available TCP port by briefly binding to port 0 on `127.0.0.1`. Returns a `Promise<number>`. Used to assign a JDWP port without port collisions.
- **`waitForPausedState()` (L63–81)**: Polls `get_stack_trace` MCP tool up to `maxAttempts` times (default 20) at `intervalMs` intervals (default 500ms). Returns the stack response when non-empty frames are found satisfying an optional `validate` predicate, or `null` on timeout. Used by both test cases to detect breakpoint hits.

### Test Suite: `MCP Server Java Attach-Mode Smoke Test @requires-java` (L83–494)

**Shared state** (L84–87):
- `mcpClient: Client | null` — MCP SDK client instance
- `transport: StdioClientTransport | null` — stdio transport to MCP server process
- `sessionId: string | null` — active debug session ID
- `jvmProcess: ChildProcess | null` — spawned JVM process

**`beforeAll` (L89–110)**: Starts MCP server as child process via `StdioClientTransport` (running `dist/index.js --log-level info`), creates and connects `Client`. Timeout: 30s.

**`afterAll` (L112–133)**: Closes debug session, MCP client, transport, and kills JVM process (SIGKILL).

**`afterEach` (L135–149)**: Closes debug session and kills JVM process between tests; resets both to null.

---

### Test 1: `should attach to a running JVM and debug with verified stack and variables` (L151–337, timeout 60s)

**Flow:**
1. Skips if `java`/`javac` not on PATH (L153–159).
2. Calls `prepareJavaExample('InfiniteWait')` (L161) to get `sourcePath`, `classDir`, `mainClass`.
3. Gets free JDWP port via `getFreePort()` (L166).
4. Spawns JVM: `java -agentlib:jdwp=transport=dt_socket,server=y,address=${jdwpPort},suspend=y -cp <classDir> <mainClass>` (L170–177).
5. Waits for `"Listening for transport"` on stdout/stderr with 15s timeout (L180–210).
6. Creates debug session via `create_debug_session` MCP tool (L216–222). Asserts `sessionId` defined.
7. Sets breakpoint at line 14 (compute method) via `set_breakpoint` (L231–238). Asserts `success: true`.
8. Attaches via `attach_to_process` with `port`, `host: '127.0.0.1'`, `sourcePaths` (L246–254). Asserts `success: true` and `state: 'paused'`.
9. Calls `continue_execution` to resume VM (L265–271). Asserts `success: true`.
10. Polls for breakpoint hit in `compute()` using `waitForPausedState` with validate predicate checking `frames[0].name` contains `"compute"` (L276–278).
11. Hard assertions: stack non-null, frames non-empty, top frame name contains `"compute"`, top frame line === 14 (L281–293).
12. Calls `get_local_variables` (L297–300). Asserts `success: true`, variables array non-empty.
13. Verifies `a === '42'` and `b === '58'` in compute() scope (L317–318).
14. Final `continue_execution` asserts `success: true` (L322–328).
15. `finally` block kills JVM (L330–336).

---

### Test 2: `should hit a breakpoint added while paused after attach` (L339–494, timeout 60s)

**Flow:**
1. Same JDK skip check (L341–347).
2. Uses `prepareJavaExample('InfiniteWait')` (L349).
3. Spawns JVM with JDWP (same pattern, L356–363).
4. Waits for `"Listening for transport"` (L366–385).
5. Creates session, asserts `sessionId` (L388–394).
6. Sets **first** breakpoint at line 14 (compute) (L398–402). Asserts `success: true`.
7. Attaches to JVM (L406–410). Asserts `success: true`.
8. First `continue_execution` (L414–418). Asserts `success: true`.
9. Polls for first breakpoint hit at `compute():14` — validates `frames[0].name` contains `"compute"` (L422–430). Hard assertions: frames non-empty, line === 14.
10. **While paused**, sets **second** breakpoint at line 19 (format method) (L434–438). Asserts `success: true`.
11. Second `continue_execution` (L442–446). Asserts `success: true`.
12. Polls for second breakpoint hit at `format():19` — validates `frames[0].name` contains `"format"` (L450–452). Hard assertions: frames non-empty, line === 19.
13. Calls `get_local_variables` (L463–466). Asserts `success: true`.
14. Verifies `label === '"Sum"'` and `value === '100'` in format() scope (L476–477).
15. Final `continue_execution` (L480–484). Asserts `success: true`.
16. `finally` kills JVM (L488–493).

---

### Key Dependencies

| Import | Usage |
|--------|-------|
| `@modelcontextprotocol/sdk/client/index.js` | MCP `Client` for tool calls |
| `@modelcontextprotocol/sdk/client/stdio.js` | `StdioClientTransport` for server process I/O |
| `./smoke-test-utils.js` | `parseSdkToolResult`, `callToolSafely` helpers |
| `./java-example-utils.js` | `prepareJavaExample` — compiles/locates Java class files |
| `child_process` | `execSync` for JDK detection, `spawn` for JVM process |
| `net` | `createServer` for free-port detection |

### MCP Tool Calls Made
- `create_debug_session` — language: `java`
- `set_breakpoint` — file path + line number
- `attach_to_process` — port, host, sourcePaths
- `continue_execution` — resumes paused VM
- `get_stack_trace` — polled to detect breakpoint hits
- `get_local_variables` — verifies runtime variable values
- `close_debug_session` — cleanup in afterAll/afterEach

### Architecture Notes
- JDI bridge handles deferred breakpoints via `ClassPrepareRequest`, so breakpoints set before attach are automatically re-registered — no manual re-send required (noted in file header and inline comment L262–263).
- JVM must emit `"Listening for transport"` string before attach is attempted; 15s timeout guards this.
- Both tests use identical JVM spawn patterns; test isolation relies on `afterEach` cleanup.
- JDWP string format: `-agentlib:jdwp=transport=dt_socket,server=y,address=${port},suspend=y`
- Variable values from JDI are returned as strings: integers as `'42'`, `'58'`, `'100'`; Java strings with quotes: `'"Sum"'`.
