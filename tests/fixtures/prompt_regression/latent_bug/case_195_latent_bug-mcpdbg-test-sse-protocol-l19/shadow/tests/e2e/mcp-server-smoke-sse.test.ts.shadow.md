# tests\e2e\mcp-server-smoke-sse.test.ts
@source-hash: 687340cf6dc51fdb
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:54Z

## MCP Server E2E SSE Smoke Test

End-to-end smoke test for the MCP server's SSE (Server-Sent Events) transport mode. Spawns a real server subprocess, connects via the MCP SDK's SSE client transport, runs a full debug sequence against `examples/python/fibonacci.py`, and verifies the result.

### Module-level State (L14–L20)
- `TEST_TIMEOUT = 30000` — 30 s timeout applied to server startup and each test case.
- `mcpSdkClient` — MCP SDK `Client` instance; reset to `null` after each test.
- `sseServerProcess` — `ChildProcess` for the spawned SSE server; reset to `null` after each test.
- `serverPort` — dynamically discovered port for the current test run.
- `projectRoot` — resolved via `process.cwd()` at module load time.
- `distReady` — module-level flag to avoid re-checking `dist/index.js` existence on every test.

### Key Internal Helpers

#### `ensureDistBuild()` (L85–L95)
Guards against running tests without a prior `npm run build`. Checks for `dist/index.js` under `projectRoot`. Sets `distReady = true` to short-circuit on subsequent calls. Throws an `Error` with actionable message if the entry is missing.

#### `findAvailablePort(): Promise<number>` (L100–L137)
Probes random ephemeral ports (49152–65535). Creates a temporary `net.Server`, binds it, closes it, then waits 200 ms (Windows port-release grace period) before resolving. Retries up to 10 times on `EADDRINUSE`/`EACCES`. Rejects on any other error or after 10 failed attempts.

#### `startSSEServer(options, maxRetries=3): Promise<number>` (L142–L261)
Calls `ensureDistBuild()`, then in a retry loop (up to `maxRetries`):
1. Calls `findAvailablePort()`.
2. Spawns `node dist/index.js sse -p <port> --log-level debug` via `child_process.spawn` with `stdio: ['ignore','pipe','pipe']`.
3. Sets a `TEST_TIMEOUT` ms timer; if the process hasn't started by then, rejects.
4. Listens for EACCES in stderr output; rejects early if found.
5. Calls `waitForHealthEndpoint(port, TEST_TIMEOUT)` asynchronously (L207–L219); resolves the promise when the health endpoint responds.
6. On `exit` before start: rejects with the exit code.
7. On EACCES retry: kills the process, waits 500 ms, tries a new port.
- Writes module-level `sseServerProcess` at L162.

### `afterEach` Cleanup (L24–L81)
- Closes `mcpSdkClient` gracefully (L28–L36).
- Sends `SIGTERM` to `sseServerProcess`, polls `exitCode` every 100 ms for up to 2 s, then escalates to `SIGKILL` if still alive (L39–L78). Uses `exitCode !== null` as the reliable termination indicator (not `proc.killed`).
- Resets `sseServerProcess`, `mcpSdkClient`, and `serverPort` to `null`.

### Test Cases

#### `'should successfully debug fibonacci.py via SSE transport'` (L263–L320)
1. Starts SSE server via `startSSEServer()`.
2. Re-checks health with `waitForHealthEndpoint`.
3. Creates `Client({ name: "e2e-sse-smoke-test-client", version: "0.1.0" })` and connects via `SSEClientTransport(http://localhost:<port>/sse)`.
4. Calls `executeDebugSequence(mcpSdkClient, fibonacciPath, 'E2E SSE Smoke Test Session')`.
5. Asserts `result.success === true`.
6. In `finally`: calls MCP tool `close_debug_session` with `{ sessionId }`.

#### `'should work when SSE server is spawned from different working directory'` (L323–L393)
Same flow, but `startSSEServer({ cwd: os.tmpdir() })` — verifies the server resolves resources correctly regardless of cwd. Uses client name `"e2e-sse-smoke-test-client-tempdir"`.

### Dependencies
- `@modelcontextprotocol/sdk/client/index.js` — `Client`
- `@modelcontextprotocol/sdk/client/sse.js` — `SSEClientTransport`
- `./smoke-test-utils.js` — `executeDebugSequence`, `waitForHealthEndpoint`
- Node built-ins: `path`, `os`, `net`, `fs.existsSync`, `child_process.spawn`

### Architectural Notes
- All server startup/teardown is co-located within the `describe` block as inner functions, referencing module-level mutable state.
- `distReady` is module-level, so it persists across multiple `it` runs within the same process — the dist check only happens once per test file execution.
- Port selection intentionally picks from the ephemeral range (49152–65535) to avoid collisions with well-known ports.
- The `waitForHealthEndpoint` call inside `startSSEServer` (L209) runs concurrently with stdout/stderr listeners; it's the primary readiness signal in production-like environments.
