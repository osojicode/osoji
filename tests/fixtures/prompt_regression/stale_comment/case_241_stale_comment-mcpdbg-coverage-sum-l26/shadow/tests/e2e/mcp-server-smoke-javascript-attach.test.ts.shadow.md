# tests\e2e\mcp-server-smoke-javascript-attach.test.ts
@source-hash: 231b4df68151152f
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:36Z

## JavaScript Attach-Mode Smoke Tests via MCP Interface

End-to-end test suite validating MCP server's `attach_to_process` behavior for JavaScript/Node.js targets, specifically addressing issue #124 (false success from attach when the js-debug child session never connected to the inspector).

### Test File Structure

- **Suite:** `MCP Server JavaScript Attach-Mode Smoke Tests` (L95–L304)
- **Target script:** `examples/javascript/attach_target.js` — a Node.js tick-loop program spawned with `--inspect` (L34)
- **Breakpoint line:** L11 of the target (`counter += 1;` inside `tick()`) (L35)

### Key Helpers

#### `getFreePort()` (L37–L51)
Allocates a free TCP port on 127.0.0.1 by opening a server on port 0, reading the assigned port, and closing immediately. Used before every `spawnTarget()` call.

#### `spawnTarget()` → `Promise<Target>` (L60–L93)
Spawns `node --inspect=127.0.0.1:<port> attach_target.js` as a child process. Waits up to 30s for `"Debugger listening on"` on stderr before resolving. Returns `{ proc, port, stdout: () => string }`. The `stdout` accessor captures cumulative stdout (used to verify continued execution after detach).

#### `createSessionAndAttach(port, extraAttachArgs)` (L154–L170)
Helper scoped to the describe block. Calls `create_debug_session` (language: `javascript`), captures `sessionId`, then calls `attach_to_process` with the given port and optional extra args (e.g., `stopOnEntry: false`). Returns the parsed attach response.

### Setup / Teardown

- **`beforeAll`** (L101–L127): Validates `dist/index.js` exists, creates `StdioClientTransport` launching the MCP server with `--log-level info`, connects an MCP `Client`. 30s timeout.
- **`afterEach`** (L129–L142): Calls `close_debug_session` for any active `sessionId`, then `SIGKILL`s the target process.
- **`afterAll`** (L144–L152): Closes MCP client and transport.

### Tests

#### Test 1: Invariant — attach must not lie (L172–L219), timeout 120s
Spawns target, attaches. If `attachResponse.success === true`, verifies `list_threads` returns ≥1 thread and `get_stack_trace` returns ≥1 frame (catching the issue #124 ghost-success pattern). If success is false, verifies the error message is non-empty. In both branches, asserts target process is still alive (exitCode === null).

#### Test 2: Full attach–breakpoint–evaluate–detach cycle (L221–L276), timeout 120s
1. Attaches with default `stopOnEntry` → expects `state === 'paused'`
2. Sets breakpoint at `BREAKPOINT_LINE` (11)
3. Continues execution, polls `get_stack_trace` up to 20 times (500ms each) for the breakpoint hit
4. Evaluates `'counter'` expression → expects numeric result ≥ 1
5. Detaches with `terminateProcess: false`, waits 2.5s, asserts target still alive and stdout has grown (resumed ticking)

#### Test 3: `stopOnEntry: false` must not pause target (L278–L304), timeout 120s
Attaches with `{ stopOnEntry: false }`, expects `state === 'running'`. Captures stdout length, waits 3s, asserts more output was produced (target kept running). Detaches, verifies target still alive.

### MCP Tools Exercised
- `create_debug_session`
- `attach_to_process`
- `list_threads`
- `get_stack_trace`
- `set_breakpoint`
- `continue_execution`
- `evaluate_expression`
- `detach_from_process`
- `close_debug_session`

### Dependencies
- `smoke-test-utils.js`: `parseSdkToolResult` (parses MCP SDK tool call responses), `callToolSafely` (wraps MCP tool calls)
- `@modelcontextprotocol/sdk`: `Client`, `StdioClientTransport`
- Node built-ins: `net`, `path`, `fs`, `child_process`

### Architectural Notes
- Each test spawns its own fresh target process via `spawnTarget()` for isolation
- `sessionId` is module-scoped and cleaned up in `afterEach` to prevent session leaks
- The `TARGET_SCRIPT` path is resolved relative to repo root (L34), requiring the example file to exist
- Server is launched from `dist/index.js` — requires a prior `npm run build`
- The `stopOnEntry` default behavior (Test 2 expects `'paused'`) implies the MCP server defaults `stopOnEntry: true` for attach
