# tests\e2e\mcp-server-smoke-javascript-attach.test.ts
@source-hash: 231b4df68151152f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:49Z

## JavaScript Attach-Mode Smoke Tests via MCP Interface

End-to-end test suite validating the `attach_to_process` MCP tool for JavaScript debugging. Addresses issue #124 where attach falsely reported success while the js-debug child session never connected to the inspector.

### Test Suite Structure

**Suite:** `MCP Server JavaScript Attach-Mode Smoke Tests` (L95–304)

Three tests all share the same MCP client lifecycle:
- `beforeAll` (L101–127): Spawns MCP server via stdio, asserts `dist/index.js` exists, connects MCP client
- `afterEach` (L129–142): Closes debug session via `close_debug_session`, kills target process with SIGKILL
- `afterAll` (L144–152): Disconnects MCP client and transport

### Key Symbols

**`getFreePort()` (L37–51):** Allocates a random free TCP port by creating/closing a server on port 0. Returns a `Promise<number>`.

**`spawnTarget()` (L60–93):** Spawns `examples/javascript/attach_target.js` with `--inspect=127.0.0.1:<port>`. Waits up to 30s for `"Debugger listening on"` on stderr. Returns `{ proc, port, stdout: () => string }`. The `stdout` closure captures live stdout from the target process for output-growth checks.

**`createSessionAndAttach(port, extraAttachArgs)` (L154–170):** Helper that:
1. Calls `create_debug_session` (language: `javascript`, name: `js-attach-test`)
2. Extracts `sessionId` from result, assigns to outer `sessionId` variable
3. Calls `attach_to_process` with `{ sessionId, host: '127.0.0.1', port, ...extraAttachArgs }`
4. Returns parsed attach response

### Tests

**Test 1 — Invariant (L172–219):** `attach_to_process` must not lie.
- Timeout: 120s
- If `attachResponse.success === true`: asserts `list_threads` returns >0 threads AND `get_stack_trace` returns >0 frames
- If attach fails: asserts error message is non-empty (truthful failure)
- Both branches: asserts target process is still running after 500ms

**Test 2 — Acceptance (L221–276):** Full attach → breakpoint → eval → detach cycle.
- Timeout: 120s
- Attaches (default `stopOnEntry`), expects `state === 'paused'`
- Sets breakpoint at `BREAKPOINT_LINE = 11` in `attach_target.js`
- Continues execution, polls `get_stack_trace` up to 20 times (×500ms = 10s) for breakpoint hit
- Evaluates expression `'counter'`, expects result ≥ 1
- Detaches with `terminateProcess: false`, waits 2.5s, asserts process alive and stdout grew

**Test 3 — `stopOnEntry:false` (L278–304):** Attach must not pause target.
- Timeout: 120s
- Attaches with `{ stopOnEntry: false }`, expects `state === 'running'`
- Waits 3s, asserts stdout grew (target kept running)
- Detaches with `terminateProcess: false`, asserts target alive

### Constants & Paths

| Symbol | Value |
|---|---|
| `ROOT` (L33) | `../../` from test dir |
| `TARGET_SCRIPT` (L34) | `<ROOT>/examples/javascript/attach_target.js` |
| `BREAKPOINT_LINE` (L35) | `11` — `counter += 1` inside `tick()` |

### Shared State (describe-scoped)
- `mcpClient: Client | null` (L96)
- `transport: StdioClientTransport | null` (L97)
- `sessionId: string | null` (L98) — managed by `createSessionAndAttach` and reset in `afterEach`
- `targetProcess: ChildProcess | null` (L99) — set per test, killed in `afterEach`

### Dependencies
- `@modelcontextprotocol/sdk/client/index.js` and `/client/stdio.js`: MCP protocol transport
- `./smoke-test-utils.js`: `parseSdkToolResult` (extracts typed payload from SDK response), `callToolSafely` (calls MCP tool, returns parsed result)
- Node.js `net`, `child_process`, `fs`: port allocation, process spawning, path checks

### MCP Tools Exercised
`create_debug_session`, `attach_to_process`, `list_threads`, `get_stack_trace`, `set_breakpoint`, `continue_execution`, `evaluate_expression`, `detach_from_process`, `close_debug_session`
