# tests\stress\cross-transport-parity.test.ts
@source-hash: 22e8131e4e902e9c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:49Z

## Cross-Transport Parity Stress Test

Validates that the MCP debug server produces identical results when accessed via STDIO and SSE transports. The entire suite is gated behind `RUN_STRESS_TESTS=true` environment variable (L17-18); if not set, the describe block is skipped via `describe.skip`.

### Key Constants
- `TEST_TIMEOUT` = 60000 ms (L20) — applied to the single integration test case
- `PROJECT_ROOT` = `process.cwd()` (L21) — used to locate `dist/index.js` and example scripts
- SSE port randomly selected in range 4500–4999 (L264)

### Interfaces
- **`DebugSequenceResult`** (L23–33): Captures outcomes of a 6-step debug sequence: session creation, breakpoint, start, stack trace, variables, and accumulated errors.
- **`TransportTestResult`** (L35–40): Wraps a `DebugSequenceResult` with transport name, success flag, and optional top-level error string.

### Class: `TransportTester` (L42–307)
Orchestrates transport setup and the debug sequence execution.

#### Methods
- **`setupSSETransport(port)`** (L45–85): Spawns `dist/index.js sse -p <port> --log-level error` as a child process. Polls `http://localhost:<port>/health` every 500ms with a 15-second overall timeout. Rejects with `'SSE server startup timeout'` if health check never passes.
- **`teardownSSE()`** (L87–96): Sends SIGTERM, waits 1s, then SIGKILL if still alive. Safe to call when `sseServer` is null.
- **`runDebugSequence(client)`** (L98–221): Executes 6 MCP tool calls in sequence against the provided `Client`:
  1. `create_debug_session` — language: `javascript`, name: `Cross-Transport Test`
  2. `set_breakpoint` — targets `examples/javascript/simple_test.js` line 11
  3. `start_debugging` — launches the test script
  4. Waits 2000ms for breakpoint hit
  5. `get_stack_trace`
  6. `get_local_variables`
  7. `close_debug_session`
  Returns `DebugSequenceResult` with counts and any errors.
- **`testStdioTransport()`** (L223–259): Creates a `StdioClientTransport` running `dist/index.js stdio --log-level error`, connects an MCP `Client`, runs `runDebugSequence`, then closes. Returns `TransportTestResult` with `transport: 'STDIO'`.
- **`testSSETransport()`** (L261–294): Picks a random port, calls `setupSSETransport`, creates `SSEClientTransport` pointing to `/sse`, runs `runDebugSequence`, then tears down in `finally`. Returns `TransportTestResult` with `transport: 'SSE'`.
- **`parseToolResponse(response)` (private)** (L296–306): Extracts `response.content[0].text` and JSON-parses it. Returns `{ success: false, error: ... }` on any malformation.

### Test Suite (L309–376)
Single `describeStress` block with one `it` case: `'should produce identical results across transports'`.

**Assertions:**
1. Both transports must succeed (`allSucceeded`, L352–353)
2. `sessionCreated`, `breakpointSet`, `debugStarted` must match between transports (L362–364)
3. Both `stackFrameCount` must be > 0 and differ by at most 1 (L367–369) — tolerates minor non-determinism
4. `variableCount` must be exactly equal (L372)

### Architecture Notes
- The test requires a pre-built `dist/index.js` (not compiled inline); must run `npm run build` first.
- The example script `examples/javascript/simple_test.js` must exist; checked via `fs.access` (L132).
- SSE port randomization (L264) reduces collision risk but does not guarantee no conflicts.
- `runDebugSequence` throws and records errors in `result.errors` rather than failing fast, allowing partial result comparison.
