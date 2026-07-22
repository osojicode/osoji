# tests\e2e\mcp-server-smoke-java-pause.test.ts
@source-hash: 5f604fd896015502
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:46Z

## Purpose
End-to-end regression smoke test for Java `PauseTest` via the MCP server interface. Specifically guards against a 2026-04-28 regression where `PauseTest.class` was compiled without `-g`, making local variables unavailable in the debugger. Verifies that `counter` is present and numeric when hitting a breakpoint inside `PauseTest`'s while-loop.

## Key Structure

### Module-level constants (L27–L29)
- `__filename`, `__dirname`, `ROOT`: ESM-compatible path resolution; `ROOT` points to project root (`../..` from `tests/e2e/`).

### `waitForPausedState` (L31–L45)
Polls `get_stack_trace` MCP tool up to `maxAttempts` times (default 30) with `intervalMs` delay (default 500ms) until `stackFrames` is non-empty. Returns the result object or `null` on timeout. Used to wait for breakpoint hit.

### `describe` block: `'MCP Server Java PauseTest Smoke Test @requires-java'` (L47–L164)
Suite-level state:
- `mcpClient: Client | null` — MCP SDK client instance
- `transport: StdioClientTransport | null` — stdio transport to `dist/index.js`
- `sessionId: string | null` — debug session ID for cleanup

**`beforeAll` (L52–L70):** Launches `dist/index.js` via `StdioClientTransport` with `NODE_ENV=test`, creates and connects `mcpClient`. 30s timeout.

**`afterAll` (L72–L82):** Closes debug session if active, then closes `mcpClient` and `transport`.

**`afterEach` (L84–L93):** Closes debug session and resets `sessionId` to `null` after each test.

### Main test case (L95–L164)
`'returns local variables from inside the PauseTest loop (regression: stale .class without -g)'` — 60s timeout.

**Flow:**
1. **JDK check (L97–L102):** Runs `java -version` and `javac -version` via `execSync`; skips test gracefully if either fails.
2. **Build (L104):** Calls `prepareJavaExample('PauseTest')` → returns `{ sourcePath, classDir, mainClass }`. Guarantees fresh `-g` compiled `.class`.
3. **Create session (L108–L113):** `create_debug_session` → stores `sessionId`.
4. **Set breakpoint (L116–L120):** `set_breakpoint` at `sourcePath` line 7 (inside while-loop after `counter++`).
5. **Start debugging (L123–L132):** `start_debugging` with `dapLaunchArgs` including `mainClass`, `classpath`, `cwd`, `stopOnEntry: false`.
6. **Wait for pause (L135–L139):** `waitForPausedState` (30 attempts × 500ms). Asserts stack exists and first frame name contains `'main'`.
7. **Check locals (L142–L158):** `get_local_variables` → finds `counter` variable, asserts it is defined and `Number.isFinite(Number(counter.value))`. This is the core regression assertion.
8. **Continue (L162–L163):** `continue_execution` → lets JVM run; `afterEach` terminates session.

## Dependencies
- `vitest` — test framework
- `@modelcontextprotocol/sdk/client/index.js` — `Client`
- `@modelcontextprotocol/sdk/client/stdio.js` — `StdioClientTransport`
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils.js` — `prepareJavaExample` (builds Java example with `-g`)
- `child_process.execSync` — JDK availability check

## MCP Tool Calls Used
| Tool | Purpose |
|---|---|
| `create_debug_session` | Start a new Java debug session |
| `set_breakpoint` | Set breakpoint at source line 7 |
| `start_debugging` | Launch Java process with DAP args |
| `get_stack_trace` | Poll for paused state |
| `get_local_variables` | Fetch locals to verify `counter` |
| `continue_execution` | Resume JVM after assertion |
| `close_debug_session` | Cleanup in afterAll/afterEach |

## Critical Invariants
- Test is self-skipping (not marked `.skip`) when JDK is absent — returns early at L101.
- The `@requires-java` tag in the suite name enables external CI filtering.
- Breakpoint at source line 7 must align with the `Thread.sleep` call inside `PauseTest`'s while-loop; a change to `PauseTest.java` could silently break line alignment.
- `parseSdkToolResult` wraps raw MCP SDK call results; `callToolSafely` swallows transport errors.
