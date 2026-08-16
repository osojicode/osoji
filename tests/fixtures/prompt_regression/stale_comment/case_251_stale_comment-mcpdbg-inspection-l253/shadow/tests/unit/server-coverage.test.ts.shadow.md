# tests\unit\server-coverage.test.ts
@source-hash: b9e825466c9c7c84
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:52Z

## Purpose
Unit test file targeting coverage gaps in `src/server.ts` — specifically error paths, edge cases, lifecycle behaviors, and the exported `coerceToolArguments` utility. Uses Vitest with a fully mocked `sessionManager` and `logger` injected via direct property assignment on the `DebugMcpServer` instance.

## Test Structure

### Setup (L12–67)
- Creates `DebugMcpServer` with `{ logLevel: 'info', logFile: '/tmp/test.log' }` config
- Injects `mockSessionManager` (covers all session/debug operations + `adapterRegistry`) and `mockLogger` via `(server as any).sessionManager` and `(server as any).logger`
- `afterEach`: `vi.clearAllMocks()`

### Test Groups

#### Session Validation Edge Cases (L69–86)
- `getSession` returning `null` → `setBreakpoint` rejects with `McpError`
- `getSession` returning `TERMINATED` lifecycle → `continueExecution` rejects with `McpError`

#### Error Handling in Tool Operations (L88–211)
- **Step operations** (`stepOver`, `stepInto`, `stepOut`, L89–132): `success: false` response propagates specific error messages
- **continueExecution failure** (L134–147): `success: false` propagates error
- **getStackTrace without proxyManager** (L149–158): throws `'Cannot get stack trace: no active proxy'`
- **getStackTrace with null threadId** (L160–178): falls back to DAP `threads` request via `sendDapRequest`, uses first thread id (5), calls `getStackTrace('test-session', 5, false)`
- **getStackTrace threads request failure** (L180–194): rejection propagates as `'Cannot get stack trace: no active proxy'`
- **getStackTrace empty threads response** (L196–210): same error

#### Create Debug Session Edge Cases (L213–252)
- `createSession` rejection → wraps with `'Failed to create debug session: ...'`
- Unsupported language in non-container mode → `"Language 'javascript' is not supported"`
- Container mode (`MCP_CONTAINER=true`) allows `python` even if not in adapter list

#### Start Debugging Edge Cases (L254–292)
- File not found via `fileChecker.checkExists` → `'Script file not found'`
- `startDebugging` rejection propagates directly

#### Set Breakpoint Edge Cases (L294–501)
- File not found → `'Breakpoint file not found'`
- `setBreakpoint` rejection propagates
- **Policy-based non-file source identifier** (L332–500): Tests `isNonFileSourceIdentifier` policy hook:
  - FQCNs (`com.example.MyClass`, `com.example.Outer$Inner`, `MyClass`) skip `fileChecker.checkExists` when policy returns `true`
  - `.java` path files still get file-checked when policy returns `false`
  - No `isNonFileSourceIdentifier` in policy → always runs file check
- **Multi-breakpoint per source file** (L667–763): Independent `setBreakpoint` calls for same/different source files work correctly

#### Server Lifecycle (L503–523)
- `server.start()` logs `'[MCP Server] Started at'`
- `server.stop()` calls `closeAllSessions`, logs `'Debug MCP Server stopped'`
- Stop with `closeAllSessions` rejection → throws

#### Adapter Registry (L525–530)
- `getAdapterRegistry()` returns `mockSessionManager.adapterRegistry`

#### Language Support Dynamic Discovery (L532–563)
- `getSupportedLanguagesAsync()` (internal method, accessed via `(server as any)`) fallback when `listLanguages` fails → uses `getSupportedLanguages()`
- No registry → defaults to `['python', 'mock']`
- Container mode adds `python` if missing

#### Successful Execution Paths (L566–621)
- `continueExecution` resolves `true` on `success: true`
- Step operations return `{ success, state }` on success
- `handleListDebugSessions` (internal) maps sessions, returns JSON `{ success, count, sessions }`
- `handlePause` (internal) throws `McpError` when `validateSession` fails

#### Get Session Name Error Handling (L623–639)
- `getSessionName` (internal) returns `'Unknown Session'` on thrown error or null session

#### Variables and Scopes Error Handling (L641–665)
- `getVariables` and `getScopes` rejections propagate

#### handleListThreads (L766–807)
- Success: JSON `{ success, threads }`
- `SessionTerminatedError` (extends `McpError`) re-thrown as `McpError`
- Generic errors wrapped as `'Failed to list threads: ...'`

#### handlePause with threadId (L809–835)
- `threadId` passed through to `sessionManager.pause('test-session', 7)`
- Missing `threadId` → `pause('test-session', undefined)`

#### Evaluate Expression Edge Cases (L837–852)
- Terminated session → returns JSON containing `'Session is terminated'` (does NOT throw)

#### handlePause (L854–901)
- Success returns `{ success, state }` JSON
- `SessionTerminatedError` re-thrown as `McpError`
- `ProxyNotRunningError` re-thrown as `McpError`
- Generic errors wrapped as `'Failed to pause execution'`

#### handleGetSourceContext (L903–993, L1123–1206)
- File found + lineReader content → JSON `{ success, file, line, lineContent, surrounding, contextLines }`
- File not found → throws `McpError` with `'Source file'` message
- `lineReader` returns `null` → JSON `{ success: false, error: '...binary or inaccessible...' }`
- Default `contextLines: 5` used when `linesContext` not specified (L975–992)

#### handleGetLocalVariables (L995–1092, L1208–1319)
- Variables with frame+scope: success JSON with `count`, `variables`, `frame`, `scopeName`
- `frame: null` → `{ message: 'No stack frames available' }`
- `frame` exists, `scopeName: null` → `{ message: 'No local scope found' }`
- `frame` + `scopeName` + empty variables → `{ message: 'The Locals scope is empty' }` / `'Locals scope is empty'`
- `McpError` with 'not paused' → graceful JSON `{ success: false, error, message }`
- Generic errors → throws `'Failed to get local variables'`
- Terminated session via `McpError` → graceful JSON `{ success: false, error: '...terminated...' }`

#### handleListSupportedLanguages (L1094–1121)
- Returns `{ installed, available, count }` from `adapterRegistry`
- `listAvailableAdapters` failure → fallback to `installed` list in simple format

### coerceToolArguments Tests (L1326–1427)
Tests the exported pure function from `src/server.ts`:
- `'null'` string → `undefined` for any field
- Numeric string → number for numeric fields (`line`, `linesContext`, `verifyTimeout`, `port`)
- `'true'`/`'false'` → boolean for boolean fields
- JSON object string → parsed object for object fields (`dapLaunchArgs`)
- JSON array string → parsed array for array fields (`args`)
- Invalid/non-matching JSON → left as-is
- `undefined` values skipped
- Already-correct types pass through
- Unknown keys ignored

## Key Patterns
- Internal methods accessed via `(server as any).methodName` pattern throughout
- `fileChecker` and `lineReader` injected via `(server as any).fileChecker` and `(server as any).lineReader`
- `validateSession` mocked via `(server as any).validateSession = vi.fn()` in some tests
- `vi.stubEnv('MCP_CONTAINER', 'true'/'undefined')` used for container mode tests
- Dynamic import of `SessionTerminatedError` within individual test (L790–791) ensures module isolation
- `mockSessionManager.listThreads`, `mockSessionManager.pause`, `mockSessionManager.getLocalVariables` added per-test (not in global mock)

## Dependencies
- `DebugMcpServer` from `../../src/server`
- `McpError`, `ErrorCode` from `@modelcontextprotocol/sdk/types.js`
- `SessionLifecycleState` from `@debugmcp/shared`
- `SessionTerminatedError`, `ProxyNotRunningError` from `../../src/errors/debug-errors.js`
