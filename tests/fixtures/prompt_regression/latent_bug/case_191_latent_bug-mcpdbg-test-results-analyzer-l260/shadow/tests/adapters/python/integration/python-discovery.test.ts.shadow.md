# tests\adapters\python\integration\python-discovery.test.ts
@source-hash: ef87c123b8e5af84
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:59Z

## Python Discovery Integration Test

Integration test verifying that the MCP server can automatically discover Python on the host system without explicit path configuration, specifically targeting Windows CI environments.

### Purpose
Tests the real `findPythonExecutable` Python discovery logic end-to-end by spinning up the actual MCP server via stdio transport and calling tools. Explicitly avoids mocking (L9 comment). Tagged `@requires-python`.

### Test Structure

**Suite:** `Python Discovery - Real Implementation Test @requires-python` (L12–L143)

**`beforeAll` (L15–L58):** Initializes an MCP `Client` connected via `StdioClientTransport` to the compiled server at `dist/index.js` (resolved relative to this test file, L19). Strips `PYTHON_PATH` and `PYTHON_EXECUTABLE` from the environment (L35–L36) to force server-side discovery. Calls `ensurePythonOnPath` (L39) to handle Windows CI where `setup-python` may not add Python to `PATH`. Passes `--log-level debug` to the server (L48). Timeout: 30 seconds.

**`afterAll` (L60–L68):** Closes client if initialized; swallows errors.

**Test: `should find Python on Windows without explicit path` (L70–L138):**
- Skips on non-Windows platforms (L71–L73).
- Calls `create_debug_session` tool with `language: 'python'`, no `pythonPath` (L94–L103).
- Calls `start_debugging` with `dryRunSpawn: true` (L117) to test the Python discovery path without actually spawning a debugger process.
- On CI failure, persists the result JSON via `persistFailurePayload` (L126).
- Asserts `startResult.success === true` and `startResult.data?.dryRun === true` (L130–L131).
- Cleans up session via `close_debug_session` (L134–L137).

### Helper: `persistFailurePayload` (L145–L154)
Writes JSON failure payload to `logs/tests/adapters/failures/<testName>-<ISO-timestamp>.json`. Called only in CI failure paths (L122–L127). Errors in this helper are caught and logged to stderr, not re-thrown.

### `parseToolResult` (L83–L90, inline helper)
Extracts and JSON-parses the first `text`-typed content item from an MCP tool call response. Throws `'Invalid ServerResult structure'` if shape is wrong.

### Key Dependencies
- `@modelcontextprotocol/sdk` — MCP `Client` and `StdioClientTransport`
- `./env-utils.js` — `ensurePythonOnPath` for Windows CI PATH fixup
- `dist/index.js` — compiled MCP server under test (must be built before running)
- `examples/python/fibonacci.py` — script path used in `start_debugging` (L110), must exist relative to cwd

### Architectural Notes
- Uses `import.meta.url` → `fileURLToPath` pattern for ESM-compatible `__dirname` (L16–L18).
- The test is platform-gated (Windows-only) to prevent false failures on Linux/macOS.
- No mocking; the test validates the actual binary discovery code path on the real OS.
- CI diagnostic logging written to `process.stderr` (L41–L44, L123–L125) to preserve output ordering.