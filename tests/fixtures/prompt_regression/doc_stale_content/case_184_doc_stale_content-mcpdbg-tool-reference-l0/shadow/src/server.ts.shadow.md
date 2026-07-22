# src\server.ts
@source-hash: db4ed3bacfbf18e7
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:11:32Z

## Overview
Primary MCP server implementation for the Debug MCP Server. Registers all MCP tools (18 tools covering the full debug lifecycle), handles tool dispatch via a `switch` on tool name, and bridges MCP protocol requests to the `SessionManager`. Also contains a type-coercion workaround for a Claude Code SSE-transport bug.

## Key Constants & Utilities (L38–168)

### `DEFAULT_LANGUAGES` (L38)
Frozen tuple `[DebugLanguage.PYTHON, DebugLanguage.MOCK]` used as the last-resort fallback when the adapter registry is unavailable.

### `getDefaultLanguages()` (L40–42)
Returns a mutable copy of `DEFAULT_LANGUAGES`.

### `ensureLanguage(languages, language)` (L44–49)
Idempotent: appends `language` to the array only if not already present. Used to guarantee Python is always advertised in container mode.

### `TOOL_ARG_EXPECTED_TYPES` (L117–130)
Static type map used by `coerceToolArguments`. Covers number/boolean/object/array fields that Claude Code may send as strings.

### `coerceToolArguments(args)` (L132–168)
**Exported.** Mutates and returns the `args` object in-place. Maps string `"null"` → `undefined`, parses numbers, booleans, and JSON strings for object/array fields. Silently ignores parse failures to let downstream validation catch them.

## Interfaces

### `DebugMcpServerOptions` (L54–57)
Exported config for the server constructor: optional `logLevel` and `logFile`.

### `LanguageMetadata` (L62–68)
Internal descriptor returned by `getLanguageMetadata()`. Fields: `id`, `displayName`, `version`, `requiresExecutable`, `defaultExecutable?`.

### `ToolArguments` (L73–107)
Internal union of all possible MCP tool parameter fields. Used as the typed cast after `coerceToolArguments`.

## `DebugMcpServer` Class (L173–1598)

### Constructor (L464–505)
1. Builds `ContainerConfig` from options; resolves `sessionLogDirBase` relative to `logFile`.
2. Calls `createProductionDependencies(containerConfig)` to get the DI container.
3. Creates `SimpleFileChecker`, `LineReader`, MCP `Server`, and `SessionManager`.
4. Calls `registerTools()` to wire up all MCP handlers.
5. Sets `server.onerror` handler.

### Private: `getSupportedLanguagesAsync()` (L182–219)
Dynamic language discovery with three-tier fallback:
1. `adapterRegistry.listLanguages()` (async, preferred)
2. `adapterRegistry.getSupportedLanguages()` (sync, registered factories)
3. `DEFAULT_LANGUAGES` (hardcoded fallback)

In container mode (`MCP_CONTAINER === 'true'`), Python is always forced into the list via `ensureLanguage`.

### Private: `getLanguageMetadata()` (L222–268)
Returns hardcoded `LanguageMetadata` for Python, Ruby, Mock, JavaScript, and a generic default. Used only in `handleListSupportedLanguages`.

### Private: `validateSession(sessionId)` (L273–282)
Throws `McpError(InvalidParams)` if session not found; throws `McpError(InvalidRequest)` if session lifecycle is `TERMINATED`.

### Public Debug Operation Methods (L285–463)
All public methods validate the session first, then delegate to `sessionManager`:
- `createDebugSession` (L285–317): Dynamic language check + session creation.
- `startDebugging` (L319–347): File existence check via `fileChecker`, passes `effectivePath` to session manager.
- `closeDebugSession` (L349–351): Direct delegation.
- `setBreakpoint` (L353–381): Skips file check for non-file source identifiers (Java FQCNs) and attach-mode sessions; otherwise checks file existence and uses `effectivePath`.
- `getVariables` (L383–386), `getStackTrace` (L388–412), `getScopes` (L414–417), `getLocalVariables` (L419–426).
- `getStackTrace` (L388–412): Falls back to DAP `threads` request if `currentThreadId` is unknown.
- `continueExecution` (L428–435), `stepOver` (L437–444), `stepInto` (L446–453), `stepOut` (L455–462).

### Private: `registerTools()` (L553–1253)
Sets two MCP request handlers:
1. **`ListToolsRequestSchema`** (L554–635): Dynamically builds tool list with supported language enum. Path descriptions are context-sensitive (container vs host).
2. **`CallToolRequestSchema`** (L637–1252): Main dispatch switch over 18 tool names. Calls `coerceToolArguments` before dispatch. Each case handles errors and maps to JSON text `content`.

Registered tools: `create_debug_session`, `list_supported_languages`, `list_debug_sessions`, `set_breakpoint`, `start_debugging`, `attach_to_process`, `detach_from_process`, `close_debug_session`, `step_over`, `step_into`, `step_out`, `continue_execution`, `pause_execution`, `list_threads`, `get_variables`, `get_local_variables`, `get_stack_trace`, `get_scopes`, `evaluate_expression`, `get_source_context`, `redefine_classes`.

### Private Handler Methods (L1255–1566)
- `handleListDebugSessions` (L1255–1276): Maps `getAllSessions()` to JSON.
- `handlePause` (L1278–1293): Validates session, calls `sessionManager.pause`.
- `handleListThreads` (L1295–1305): Validates session, calls `sessionManager.listThreads`.
- `handleEvaluateExpression` (L1307–1368): Expression length guard (10KB), delegates to `sessionManager.evaluateExpression`.
- `handleGetSourceContext` (L1370–1434): File existence check + `lineReader.getLineContext`.
- `handleGetLocalVariables` (L1436–1520): Validates session, calls `getLocalVariables`, adds edge-case messages for empty results.
- `handleListSupportedLanguages` (L1522–1566): Combines `listLanguages`, `listAvailableAdapters`, and `getLanguageMetadata` into one payload.

### Public Lifecycle Methods (L1571–1587)
- `start()` (L1571–1575): Logs startup; transport connection is external.
- `stop()` (L1577–1580): Calls `sessionManager.closeAllSessions()`.
- `getAdapterRegistry()` (L1585–1587): Exposes `sessionManager.adapterRegistry` for tests/external use.

### Private: `filterDisabledLanguages(languages, disabled?)` (L1589–1598)
Filters disabled languages from a list using a `Set<string>`. Falls back to `getDisabledLanguages()` if set not provided.

## Key Architectural Patterns
- **Container-mode path resolution**: `fileChecker.checkExists` returns `effectivePath` (container-remapped), which is passed downstream instead of the original path.
- **SSE type coercion**: `coerceToolArguments` is called on every `CallTool` request to handle the Claude Code SSE bug.
- **Session error soft-handling**: Session-related errors (terminated, not found, proxy not running) are caught per-tool and returned as `{ success: false, error }` JSON rather than thrown; other errors are rethrown as `McpError`.
- **Attach-mode file skip**: `setBreakpoint` skips host-side file existence checks for attach sessions.
- **Pending steps**: Step tools propagate `pending: true` in the response when a step takes >5s.