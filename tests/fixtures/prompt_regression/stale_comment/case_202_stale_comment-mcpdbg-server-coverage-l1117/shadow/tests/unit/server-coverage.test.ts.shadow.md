# tests\unit\server-coverage.test.ts
@source-hash: b9e825466c9c7c84
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:09Z

## Purpose
Targeted unit test suite for `server.ts` covering error paths, edge cases, and the exported `coerceToolArguments` pure function. Uses Vitest with mocked `sessionManager`, `logger`, `fileChecker`, and `lineReader` internals injected via `(server as any)`.

## Test Structure

### Setup (L17–67)
- `beforeEach` creates a `DebugMcpServer` instance with `logLevel: 'info'` and `logFile: '/tmp/test.log'`, then replaces `server.sessionManager` and `server.logger` with `vi.fn()` mocks via `(server as any)`.
- `mockSessionManager` (L33–58) models the full session manager API including `adapterRegistry` with `getSupportedLanguages`, `listLanguages`, and `listAvailableAdapters`.
- `afterEach` calls `vi.clearAllMocks()`.

### Session Validation Edge Cases (L69–86)
- Session not found → `McpError` thrown from `setBreakpoint` (L70–75)
- Terminated session → `McpError` thrown from `continueExecution` (L77–85)

### Error Handling in Tool Operations (L88–211)
- `stepOver`, `stepInto`, `stepOut`, `continueExecution` failures: mock returns `{ success: false, error: '...' }` → method re-throws the error message string (L89–147)
- `getStackTrace` without `proxyManager` → throws `'Cannot get stack trace: no active proxy'` (L149–158)
- `getStackTrace` with null thread ID: falls back to DAP `threads` request, uses `threads[0].id` (L160–178)
- `getStackTrace` when threads request rejects → throws same proxy error (L180–194)
- `getStackTrace` when threads response is empty array → throws same proxy error (L196–210)

### Create Debug Session Edge Cases (L213–252)
- `createSession` rejection wraps error: `'Failed to create debug session: Port allocation failed'` (L214–221)
- Unsupported language in non-container mode → `"Language 'javascript' is not supported"` (L223–231)
- Container mode (`MCP_CONTAINER=true`): allows `python` even if not in `listLanguages` result (L233–251)

### Start Debugging Edge Cases (L254–292)
- File not found via `fileChecker.checkExists({ exists: false })` → throws `'Script file not found'` (L255–271)
- `startDebugging` rejection → error propagates directly (L274–291)

### Set Breakpoint Edge Cases (L294–500)
- File not found → throws `'Breakpoint file not found'` (L295–311)
- `setBreakpoint` rejection → error propagates (L313–329)
- Policy with `isNonFileSourceIdentifier` returning `true` → skips `fileChecker.checkExists` for class names like `com.example.MyClass`, `com.example.Outer$Inner`, `MyClass` (L332–419)
- Policy `isNonFileSourceIdentifier` returning `false` for `.java` paths → file check IS performed (L421–449)
- Policy without `isNonFileSourceIdentifier` → always performs file check (L451–477)
- Non-file-path input without policy support → file check run, fails → `'Breakpoint file not found'` (L479–500)

### Server Lifecycle (L503–523)
- `start()` logs `'[MCP Server] Started at'` (L504–507)
- `stop()` calls `closeAllSessions` and logs `'Debug MCP Server stopped'` (L509–516)
- `stop()` with `closeAllSessions` rejection → propagates error (L518–522)

### Get Adapter Registry (L525–530)
- `getAdapterRegistry()` returns `mockSessionManager.adapterRegistry`

### Language Support Dynamic Discovery (L532–564)
- `getSupportedLanguagesAsync()` fallback on `listLanguages` failure → uses `getSupportedLanguages` synchronously + logs warning (L533–543)
- No registry available (`adapterRegistry: undefined`) → returns default `['python', 'mock']` (L545–552)
- Container mode: injects `python` if missing from registry result (L554–563)

### Successful Execution Paths (L566–621)
- `continueExecution` resolves to `true` when session manager returns `{ success: true }` (L575–579)
- `stepOver/stepInto/stepOut` resolve to `{ success: true, state: 'paused' }` (L582–590)
- `handleListDebugSessions` maps sessions and returns JSON `{ success, count, sessions }` (L592–613)
- `handlePause` throws `McpError` when `validateSession` throws (L615–620)

### Get Session Name Error Handling (L623–639)
- `getSessionName` returns `'Unknown Session'` when `getSession` throws or returns null

### Variables and Scopes Error Handling (L641–665)
- `getVariables` and `getScopes` propagate underlying errors

### Multi-Breakpoint per Source File (L667–763)
- Multiple `setBreakpoint` calls on same source file each reach `mockSessionManager.setBreakpoint` independently (L679–711)
- Return value from `setBreakpoint` includes `id`, `verified`, `line`, `message` (L713–731)
- Different source files don't interfere (L733–763)

### handleListThreads (L766–807)
- Returns JSON `{ success, threads }` on success (L767–783)
- Re-throws `SessionTerminatedError` (extends `McpError`) (L785–795)
- Wraps generic errors as `McpError` with `'Failed to list threads: ...'` (L797–806)

### handlePause (L809–901)
- Passes `threadId` (L810–822) or `undefined` (L824–834) to `sessionManager.pause`
- Returns JSON `{ success, state }` (L855–867)
- Re-throws `SessionTerminatedError` and `ProxyNotRunningError` as `McpError` (L869–889)
- Wraps generic errors as `'Failed to pause execution'` (L891–900)

### handleEvaluateExpression (L837–852)
- Terminated session → returns graceful JSON with `'Session is terminated'` in content (not throws)

### handleGetSourceContext (L903–993, L1123–1206)
- Success: returns JSON `{ success, file, line, lineContent, surrounding, contextLines }` (L911–938)
- File not found → throws `McpError` with `'Source file'` (L940–954)
- `lineReader.getLineContext` returns `null` → returns JSON `{ success: false, error: 'Could not read source context' / 'binary or inaccessible' }` (L956–973, L1124–1150)
- Default `contextLines: 5` when not specified (L975–992)
- Respects `linesContext` parameter (L1152–1184)

### handleGetLocalVariables (L995–1092, L1208–1319)
- Returns variables with `frame`, `scopeName`, `count` (L1004–1021, L1274–1297)
- No frame → `'No stack frames available'` message (L1023–1038, L1209–1230)
- Frame but no scope → `'No local scope found'` message (L1040–1053, L1232–1251)
- Scope but no variables → `'The Locals scope is empty'` / `'Locals scope is empty'` (L1055–1068, L1253–1272)
- `McpError` with `'not paused'` → graceful JSON error (L1070–1083)
- Terminated session (`McpError` with `'terminated'`) → graceful JSON (L1299–1318)
- Generic errors → throws `'Failed to get local variables'` (L1085–1091)

### handleListSupportedLanguages (L1094–1121)
- Returns `{ success, installed, available, count }` with adapter metadata (L1095–1105)
- Falls back to simple format when `listAvailableAdapters` fails (L1107–1120)

### coerceToolArguments (L1326–1427)
Standalone `describe` block for the exported pure function `coerceToolArguments`. Loaded dynamically via `import('../../src/server.js')` in `beforeEach`.
- `'null'` string → `undefined` (L1334–1338)
- Numeric string fields (`line`, `linesContext`, `verifyTimeout`, `port`) → `number` (L1340–1351)
- Empty / non-numeric string → left as-is (L1353–1363)
- `'true'`/`'false'` → boolean (L1365–1370); other strings left as-is (L1372–1376)
- JSON object string for `dapLaunchArgs` → parsed object (L1378–1382); non-object JSON left as-is (L1384–1388)
- JSON array string for `args` → parsed array (L1390–1394); non-array JSON left as-is (L1396–1400)
- Invalid JSON left as-is (L1402–1406)
- `undefined` values skipped (L1408–1413)
- Already-correct types left unchanged (L1415–1420)
- Unknown keys ignored (L1422–1426)

## Key Architectural Patterns
- Internal server methods tested via `(server as any).methodName()` — covers private handlers like `handlePause`, `handleListThreads`, `handleGetSourceContext`, `handleGetLocalVariables`, `handleListDebugSessions`, `getSupportedLanguagesAsync`, `getSessionName`, `validateSession`
- `fileChecker` and `lineReader` injected as `(server as any).fileChecker/lineReader` to control I/O
- `MCP_CONTAINER` env var tested via `vi.stubEnv`
- Dynamic import used in some tests to get fresh module references (L790, L1306, L1329–1331)

## Dependencies
- `DebugMcpServer` from `../../src/server`
- `McpError`, `ErrorCode` from `@modelcontextprotocol/sdk/types.js`
- `SessionLifecycleState` from `@debugmcp/shared`
- `SessionTerminatedError`, `ProxyNotRunningError` from `../../src/errors/debug-errors.js`