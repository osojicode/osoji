# tests\e2e\mcp-server-smoke-java-event-race.test.ts
@source-hash: 7b8b21d49d204a4f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:06Z

## Java Event Loop Race Condition Smoke Test

End-to-end test verifying a JDI (Java Debug Interface) bug fix: when a `ClassPrepareEvent` arrives in the same `EventSet` as a `BreakpointEvent` with `suspendPolicy="thread"`, the stopped thread must NOT be incorrectly resumed. Before the fix, this caused `"Thread has been resumed"` errors on `evaluate_expression`.

### Test Structure

**Suite:** `Java Event Loop Race Condition Fix @requires-java` (L47–234)

**Setup / Teardown:**
- `beforeAll` (L59–72): Spawns MCP server via `StdioClientTransport` pointing to `dist/index.js`, connects `mcpClient`. 30s timeout.
- `afterAll` (L74–80): Closes debug session, MCP client, and transport.
- `afterEach` (L82–87): Closes any open debug session and resets `sessionId` to `null`.

### Key Helper

**`waitForPausedState`** (L31–45): Polls `get_stack_trace` tool up to `maxAttempts` times (default 20) with `intervalMs` delay (default 500ms). Returns stack trace result when `stackFrames` is non-empty, or `null` on timeout. Used to await breakpoint hits.

### Single Test Case (L89–234, timeout: 90s)

`'should not resume thread when ClassPrepareEvent coincides with BreakpointEvent (suspendPolicy=thread)'`

**Flow:**
1. **JDK check** (L91–97): Skips gracefully if `java`/`javac` not on PATH.
2. **Prepare Java sources** (L99–104): Calls `prepareJavaExample('EventRaceTest')` to compile `EventRaceTest` + `LateLoadedHelper`. Sets `testJavaDir`, `mainFile`, `helperFile`, `mainClass`.
3. **Create session** (L107–112): `create_debug_session` → `language='java'`, name `'java-event-race'`.
4. **Breakpoint 1** (L117–126): `set_breakpoint` on `EventRaceTest.java` line 21, `suspendPolicy='thread'` — hits `compute()`.
5. **Breakpoint 2** (L133–142): `set_breakpoint` on `LateLoadedHelper.java` line 8, `suspendPolicy='thread'` — deferred (class not yet loaded → `ClassPrepareRequest`).
6. **Start debugging** (L146–160): `start_debugging` with `dapLaunchArgs` including `mainClass`, `classpath`, `cwd`, `stopOnEntry: false`.
7. **Wait for BP1** (L164): `waitForPausedState` with 30 attempts × 500ms. Asserts frame name contains `'compute'`.
8. **CRITICAL evaluate** (L175–184): `evaluate_expression` with `'a + b'` — expects `success=true`, `result='30'`. This is the regression assertion.
9. **Local variables** (L187–195): `get_local_variables` — asserts `a='10'`, `b='20'`.
10. **Continue** (L199–203): `continue_execution` → `success=true`.
11. **Wait for BP2** (L207–212): `waitForPausedState` 20 × 500ms. Asserts frame name contains `'greet'`.
12. **Evaluate in greet()** (L215–224): `evaluate_expression('name')` → expects `result='"World"'`.
13. **Continue to finish** (L227–231): Final `continue_execution`.

### Dependencies
- `prepareJavaExample` from `./java-example-utils.js`: Compiles Java sources and returns `{ classDir, sourcePath, mainClass }`.
- `parseSdkToolResult`, `callToolSafely` from `./smoke-test-utils.js`: Unwrap MCP SDK tool call responses.
- `@modelcontextprotocol/sdk`: `Client` and `StdioClientTransport` for MCP server communication.

### MCP Tools Exercised
`create_debug_session`, `set_breakpoint`, `start_debugging`, `get_stack_trace`, `evaluate_expression`, `get_local_variables`, `continue_execution`, `close_debug_session`

### Architecture Notes
- Uses module-scope `let` variables (`mcpClient`, `transport`, `sessionId`, `testJavaDir`, etc.) shared across lifecycle hooks and the test body.
- `helperFile` is derived manually as `path.join(testJavaDir, 'LateLoadedHelper.java')` (L102) rather than from `prepareJavaExample` — assumes both files land in the same `classDir`.
- `ROOT` (L29) resolves to repo root (`../..` from `tests/e2e/`), used to locate `dist/index.js`.
- `@requires-java` tag in suite name signals CI tagging convention for conditional execution.
