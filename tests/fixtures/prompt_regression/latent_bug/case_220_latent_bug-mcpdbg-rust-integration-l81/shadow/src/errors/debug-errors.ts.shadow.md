# src\errors\debug-errors.ts
@source-hash: ffa3c12d6090411b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:41Z

## Typed Error Hierarchy for MCP Debugger

Defines a structured, typed error hierarchy extending `McpError` from the MCP SDK. Replaces fragile string-based error detection with semantic error classes carrying structured metadata. All errors propagate `McpErrorCode` values directly to the MCP protocol layer.

### Architecture
All custom errors extend `McpError` (from `@modelcontextprotocol/sdk/types.js`), which itself extends `Error`. Each class stores structured data both as typed fields (for programmatic access) and as the third `data` argument to `McpError` (for protocol serialization).

### Error Classes

**`LanguageRuntimeNotFoundError` (L17–30)**
- Base class for missing language runtime executables
- Fields: `language: string`, `executablePath: string`
- MCP code: `InvalidParams`
- Data payload: `{ language, executablePath }`

**`PythonNotFoundError` (L35–39)**
- Specialization of `LanguageRuntimeNotFoundError` for Python
- Hardcodes `language = 'Python'`; accepts only `pythonPath: string`

**`SessionNotFoundError` (L44–55)**
- Thrown when a session ID cannot be resolved
- Fields: `sessionId: string`
- MCP code: `InvalidParams`
- Data payload: `{ sessionId }`

**`SessionTerminatedError` (L60–73)**
- Thrown when an operation is attempted on a terminated session
- Fields: `sessionId: string`, `state: string` (default: `'TERMINATED'`)
- MCP code: `InvalidRequest`
- Data payload: `{ sessionId, state }`

**`UnsupportedLanguageError` (L78–91)**
- Thrown when a requested language is not supported
- Fields: `language: string`, `availableLanguages: string[]`
- MCP code: `InvalidParams`
- Data payload: `{ language, availableLanguages }`
- Message includes comma-joined list of available languages

**`ProxyNotRunningError` (L96–109)**
- Thrown when an operation requires an active proxy but none exists
- Fields: `sessionId: string`, `operation: string`
- MCP code: `InvalidRequest`
- Data payload: `{ sessionId, operation }`

**`DebugSessionCreationError` (L114–131)**
- Thrown when session creation fails
- Fields: `reason: string`, `originalError?: Error`
- MCP code: `InternalError`
- Data payload: `{ reason, originalMessage, originalStack }` — wraps original error details

### Utility

**`getErrorMessage(error: unknown): string` (L136–141)**
- Safe error message extractor; handles both `Error` instances and arbitrary thrown values
- Returns `error.message` for `Error` instances, `String(error)` otherwise

### Re-exports
- `McpErrorCode` (aliased from `ErrorCode`) re-exported at L11 for consumer convenience — avoids direct SDK import in calling code.