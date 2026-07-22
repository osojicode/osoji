# tests\e2e\mcp-server-smoke-dotnet.test.ts
@source-hash: a553b94f47e3a6f0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:05Z

## Purpose
End-to-end smoke test for the .NET/C# debugging adapter via the MCP (Model Context Protocol) interface. Validates the full debugging lifecycle using a real `netcoredbg` backend against an example .NET console app.

## Test Structure

### Prerequisites / Environment Setup (L35–82)
- **`hasDotnetDebugSupport()` (L35–54)**: Checks availability of both `dotnet` CLI and `netcoredbg` debugger. Looks for `netcoredbg` via `NETCOREDBG_PATH` env var (with `existsSync` check) or falls back to PATH discovery. Returns `false` if either is missing.
- **`SKIP_DOTNET` (L56)**: Module-level constant; drives `describe.skipIf` to skip the entire suite when prerequisites are absent.
- **`ensureDotnetBuild()` (L61–82)**: Resolves the built `dotnet.dll` from `examples/dotnet/bin/Debug/<tfm>/dotnet.dll`. Tries TFMs `net10.0` → `net6.0` in order. Builds the project via `dotnet build -c Debug` if no pre-built artifact exists. Throws if the DLL still can't be found after build.

### Test Suite: `.NET Adapter Smoke Test` (L84–293)
Conditionally skipped via `describe.skipIf(SKIP_DOTNET)`.

**Shared state:**
- `mcpClient: Client | null` — MCP SDK client instance
- `transport: StdioClientTransport | null` — stdio transport to MCP server process
- `sessionId: string | null` — active debug session ID, reset in `afterEach`

**Lifecycle hooks:**
- **`beforeAll` (L89–110)**: Spawns MCP server (`dist/index.js`) as a child process via `StdioClientTransport`, creates a `Client` named `dotnet-smoke-test-client`, connects. 30 s timeout.
- **`afterAll` (L112–129)**: Attempts graceful `close_debug_session`, then closes `mcpClient` and `transport`.
- **`afterEach` (L131–140)**: Closes session if still open, resets `sessionId` to `null`.

**Tests:**
1. **`should list dotnet as a supported language` (L142–156)**: Calls `list_supported_languages`, asserts `dotnet` language ID is present.
2. **`should complete .NET debugging flow` (L158–292)**: Full 8-step integration flow (60 s timeout):
   - Step 1 (L163–175): `create_debug_session` with `language: 'dotnet'` → captures `sessionId`
   - Step 2 (L177–191): `set_breakpoint` at `Program.cs:14` (int x = 10;)
   - Step 3 (L193–213): `start_debugging` with compiled DLL path, `stopOnEntry: false`, `justMyCode: true`; calls `skipIfSpawnBlocked` on failure to soft-skip instead of hard-fail
   - Step 4 (L216–231): 8 s wait → `get_stack_trace` → logs top frame location
   - Step 5 (L233–268): `get_scopes` for top frame → `get_variables` for `Locals` scope; asserts `x === '0'` (uninitialized before assignment at line 14)
   - Step 6 (L271–276): `step_over`, 2 s wait
   - Step 7 (L279–283): `continue_execution`, 3 s wait
   - Step 8 (L285–289): `close_debug_session` → asserts success, clears `sessionId`

## Key Dependencies
- `@modelcontextprotocol/sdk/client/index.js` — `Client` class for MCP tool calls
- `@modelcontextprotocol/sdk/client/stdio.js` — `StdioClientTransport` for child process communication
- `./smoke-test-utils.js` — `parseSdkToolResult` (parses MCP SDK response into plain object), `callToolSafely` (non-throwing tool call wrapper)
- `../test-utils/helpers/adapter-spawn.js` — `skipIfSpawnBlocked` (conditionally skips test if spawn fails, e.g., in CI)

## MCP Tools Exercised
`list_supported_languages`, `create_debug_session`, `set_breakpoint`, `start_debugging`, `get_stack_trace`, `get_scopes`, `get_variables`, `step_over`, `continue_execution`, `close_debug_session`

## Notable Patterns
- **Graceful degradation**: Uses `callToolSafely` for post-launch steps to avoid hard failures if session is already in a bad state.
- **Spawn-block skipping**: `skipIfSpawnBlocked(ctx, startResponse, '.NET')` at L210 provides CI-friendly soft-skip when adapter binary is unavailable, rather than failing.
- **TFM probe order**: `ensureDotnetBuild` probes from `net10.0` down to `net6.0`, making tests forward-compatible with newer SDK releases.
- **Fixed waits**: Uses raw `setTimeout` (8 s for breakpoint, 2 s after step, 3 s after continue) rather than event polling — can be flaky on slow machines.
- **ESM `__dirname` polyfill**: `fileURLToPath`/`path.dirname` pattern at L28–29 for ESM compatibility.
