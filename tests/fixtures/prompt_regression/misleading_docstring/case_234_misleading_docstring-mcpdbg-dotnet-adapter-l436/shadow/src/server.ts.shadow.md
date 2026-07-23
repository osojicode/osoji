# src\server.ts
@source-hash: db4ed3bacfbf18e7
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:37Z

## Overview

Primary implementation file for the Debug MCP Server. Exposes a `DebugMcpServer` class that wraps the MCP SDK `Server`, registers all debugger tool handlers, and orchestrates `SessionManager` for lifecycle operations (create, start, step, attach, detach, close sessions).

---

## Key Exports

### `DebugMcpServerOptions` (L54–57)
Config interface with optional `logLevel` and `logFile`. Passed to constructor; used to build `ContainerConfig` for dependency injection.

### `coerceToolArguments` (L132–168)
**Critical utility.** Works around a Claude Code SSE-transport bug (anthropics/claude-code#11359) where JSON-typed tool arguments arrive as strings. Mutates and returns the `args` record in-place:
- Converts `"null"` string → `undefined`
- Numbers: `Number(val)` if non-empty and non-NaN
- Booleans: `"true"/"false"` → `true/false`
- Objects/arrays: `JSON.parse` with type validation
- Only processes keys present in `TOOL_ARG_EXPECTED_TYPES` (L117–130)

### `DebugMcpServer` (L173–1598)
Main server class. Key responsibilities:
- **Constructor (L464–505):** Builds `ContainerConfig`, calls `createProductionDependencies`, instantiates `SessionManager`, `SimpleFileChecker`, `LineReader`, creates MCP `Server`, calls `registerTools()`.
- **`registerTools()` (L553–1253):** Registers `ListToolsRequestSchema` and `CallToolRequestSchema` handlers. `ListTools` is dynamic — generates `enum` of supported languages at request time. `CallTools` dispatches to 18 tool cases via a `switch`.
- **`getSupportedLanguagesAsync()` (L182–219):** Discovers languages dynamically from adapter registry's `listLanguages()`, falls back to `getSupportedLanguages()`, then to `DEFAULT_LANGUAGES`. Always filters disabled languages. In container mode (`MCP_CONTAINER=true`), ensures `python` is always included.
- **`validateSession()` (L273–282):** Throws `McpError` if session not found or `SessionLifecycleState.TERMINATED`.
- **File resolution pattern:** `fileChecker.checkExists()` used before `startDebugging` and `setBreakpoint` to validate path existence. Attach-mode sessions skip file checks (L366–369). Non-file source identifiers (Java FQCNs) also skip file checks (L357–361).

---

## Tool Handlers (all inside `registerTools` switch, L655–1223)

| Tool | Handler location |
|---|---|
| `create_debug_session` | L656–735 (inline, supports attach-mode shortcut) |
| `list_debug_sessions` | `handleListDebugSessions()` L1255–1276 |
| `set_breakpoint` | L740–824 (inline, includes line context enrichment) |
| `start_debugging` | L826–868 (inline) |
| `attach_to_process` | L870–923 (inline) |
| `detach_from_process` | L924–968 (inline) |
| `close_debug_session` | L970–988 (inline) |
| `step_over/into/out` | L990–1070 (shared case, includes line context enrichment) |
| `continue_execution` | L1072–1094 (inline) |
| `pause_execution` | `handlePause()` L1278–1293 |
| `list_threads` | `handleListThreads()` L1295–1305 |
| `get_variables` | L1107–1143 (inline) |
| `get_stack_trace` | L1145–1171 (inline) |
| `get_scopes` | L1173–1192 (inline) |
| `evaluate_expression` | `handleEvaluateExpression()` L1307–1368 |
| `get_source_context` | `handleGetSourceContext()` L1370–1434 |
| `get_local_variables` | `handleGetLocalVariables()` L1436–1520 |
| `list_supported_languages` | `handleListSupportedLanguages()` L1522–1566 |
| `redefine_classes` | L1210–1220 (inline, Java hot-swap) |

---

## Error Handling Patterns

- Session-state errors (`terminated`, `closed`, `not found`) in most tool handlers are caught and returned as `{ success: false, error }` JSON responses (not thrown as MCP errors), allowing graceful degradation.
- File-not-found → `McpError(InvalidParams)` with container hint if in container mode (L545–551).
- `McpError` instances are re-thrown as-is; other errors are wrapped in `McpError(InternalError)`.
- `getStackTrace` (L394–412): If `currentThreadId` is not a number, issues a DAP `threads` request and uses `threads[0].id` as fallback.

---

## Lifecycle Methods

- **`start()` (L1571–1575):** Logs startup; transport attachment is handled externally.
- **`stop()` (L1577–1580):** Calls `sessionManager.closeAllSessions()`.
- **`getAdapterRegistry()` (L1585–1587):** Exposes `sessionManager.adapterRegistry` publicly for testing/external use.

---

## Internal Helpers

- **`sanitizeRequest()` (L510–521):** Redacts absolute `executablePath` and truncates `args` arrays >5 for logging.
- **`getPathDescription()` (L535–543):** Returns container-aware path description for tool schema.
- **`fileNotFoundError()` (L545–551):** Builds `McpError` with container Docker volume hint.
- **`filterDisabledLanguages()` (L1589–1598):** Filters language list against disabled set from env config.
- **`getDefaultLanguages()` (L40–42):** Returns `['python', 'mock']`.
- **`ensureLanguage()` (L44–49):** Idempotently appends a language to a list.

---

## Key Constants

- `DEFAULT_LANGUAGES` (L38): `[DebugLanguage.PYTHON, DebugLanguage.MOCK]` — frozen array.
- `TOOL_ARG_EXPECTED_TYPES` (L117–130): Schema map for SSE type coercion.

---

## Architectural Notes

- **Dependency injection:** All I/O dependencies come from `createProductionDependencies(containerConfig)` (L471).
- **Container mode:** `process.env.MCP_CONTAINER === 'true'` gates path resolution and language list enforcement throughout.
- **Dynamic tool schema:** `list_supported_languages` enum is computed at request time, not at server init, allowing runtime adapter registration to affect the advertised tool schema.
- **Line context enrichment:** After `set_breakpoint` and step commands, the server opportunistically fetches surrounding source lines via `lineReader.getLineContext()` and includes them in the response.
- **`getStackTrace` public method (L388–412):** Adds thread-discovery fallback logic not present in `SessionManager.getStackTrace` directly — this is the correct entry point for stack trace retrieval.
