# tests\e2e\mcp-server-smoke-java-pause.test.ts
@source-hash: 5f604fd896015502
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:51Z

## Purpose
End-to-end smoke/regression test that verifies the Java `PauseTest` class is compiled with `-g` (debug symbols), allowing local variables to be inspected at a breakpoint hit inside a `while(true)` loop via the MCP debugger interface.

## Regression Context
Introduced to catch a 2026-04-28 bug: `PauseTest.class` existed on disk compiled without `-g`, so local variables (specifically `counter`) were either missing or returned as a sentinel string. The test ensures `prepareJavaExample` always produces a fresh `-g`-compiled `.class`.

## Key Elements

### `waitForPausedState` (L31–45)
Polls `get_stack_trace` MCP tool up to `maxAttempts` (default 30) times with `intervalMs` (default 500ms) delay. Returns the stack-trace result object (with `stackFrames` array) once paused, or `null` on timeout. Used to wait for the JVM to hit the breakpoint.

### `describe` block: `'MCP Server Java PauseTest Smoke Test @requires-java'` (L47–165)
Main test suite. Lifecycle:
- **`beforeAll`** (L52–70): Spawns MCP server as child process (`dist/index.js --log-level info`), connects `Client` via `StdioClientTransport`. 30s timeout.
- **`afterAll`** (L72–82): Attempts `close_debug_session`, then closes MCP client and transport.
- **`afterEach`** (L84–93): Closes any open debug session and nulls `sessionId`.

### Main test case (L95–164): `'returns local variables from inside the PauseTest loop (regression: stale .class without -g)'`
Sequence:
1. **JDK guard** (L97–102): Runs `java -version` and `javac -version` via `execSync`; skips silently if either fails.
2. **Build** (L104): `prepareJavaExample('PauseTest')` returns `{ sourcePath, classDir, mainClass }`.
3. **create_debug_session** (L108–113): MCP tool call; asserts `sessionId` defined.
4. **set_breakpoint** (L116–120): Targets `sourcePath` line 7 (inside while-loop after `counter++`).
5. **start_debugging** (L123–132): `dapLaunchArgs` includes `mainClass`, `classpath: classDir`, `cwd: classDir`, `stopOnEntry: false`.
6. **waitForPausedState** (L135): Polls up to 30 attempts × 500ms = 15s.
7. **Stack frame assertion** (L137–139): `frames[0].name` must contain `'main'` (case-insensitive).
8. **get_local_variables** (L142–157): Asserts `counter` variable present AND its value parses as a finite number — the regression assertion against sentinel string.
9. **continue_execution** (L162–163): Resumes JVM; afterEach closes session.
- Test timeout: 60s.

## Dependencies
- `@modelcontextprotocol/sdk/client/index.js` — `Client` class for MCP communication
- `@modelcontextprotocol/sdk/client/stdio.js` — `StdioClientTransport` for subprocess MCP server
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely` helpers
- `./java-example-utils.js` — `prepareJavaExample` (ensures fresh `-g` compiled `.class`)

## MCP Tool Calls Made
| Tool | Purpose |
|---|---|
| `create_debug_session` | Start a new debug session |
| `set_breakpoint` | Set breakpoint at source line 7 |
| `start_debugging` | Launch JVM with DAP args |
| `get_stack_trace` | Poll for paused state |
| `get_local_variables` | Inspect `counter` local variable |
| `continue_execution` | Resume JVM after assertion |
| `close_debug_session` | Cleanup in afterAll/afterEach |

## Architectural Patterns
- MCP server launched as real subprocess (`dist/index.js`); not mocked.
- JDK availability checked at runtime via `execSync`; graceful skip pattern instead of `test.skip`.
- `sessionId` stored in closure shared across lifecycle hooks for cleanup.
- Non-null assertions (`mcpClient!`, `sessionId`, `stack!`) used intentionally after existence checks.
