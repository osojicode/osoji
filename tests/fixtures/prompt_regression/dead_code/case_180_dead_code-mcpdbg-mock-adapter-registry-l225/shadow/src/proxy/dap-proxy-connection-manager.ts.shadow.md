# src\proxy\dap-proxy-connection-manager.ts
@source-hash: 1d69bccf356607b0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:30Z

## DapConnectionManager (L16–294)

Manages the lifecycle of a Debug Adapter Protocol (DAP) connection: initial TCP connection with retry logic, session initialization, event handler wiring, launch/attach request dispatch, breakpoint configuration, and graceful disconnection.

### Class: `DapConnectionManager` (L16–294)

**Constructor (L24–27):** Accepts `IDapClientFactory` and `ILogger`. Policy is set separately via `setAdapterPolicy`.

**Key Constants:**
- `INITIAL_CONNECT_DELAY = 500` ms (L19) — warm-up pause before first connect attempt, important for slow adapters (e.g., debugpy in CI)
- `MAX_CONNECT_ATTEMPTS = 60` (L20)
- `CONNECT_RETRY_INTERVAL = 200` ms (L21)

**Methods:**

| Method | Lines | Purpose |
|---|---|---|
| `setAdapterPolicy` | L32–34 | Stores `AdapterPolicy`; used in `connectWithRetry` to pass policy to factory |
| `connectWithRetry` | L39–79 | Creates `IDapClient` (with or without policy), registers a temporary error handler, then loops up to 60 attempts (200 ms apart) calling `client.connect()`. Removes temp error handler on success or final failure. |
| `initializeSession` | L84–100 | Sends DAP `initialize` request with fixed args: `clientID=mcp-proxy-{sessionId}`, `clientName=MCP Debug Proxy`, `adapterID` defaults to `'python'`, `pathFormat=path`, lines/columns at 1, etc. |
| `setupEventHandlers` | L105–156 | Conditionally registers up to 9 DAP event listeners (`initialized`, `output`, `stopped`, `continued`, `thread`, `exited`, `terminated`, `error`, `close`) on the client. |
| `disconnect` | L161–192 | Sends DAP `disconnect` request (1 s timeout via `Promise.race`), then always calls `client.disconnect()` for socket cleanup. No-ops if `client` is `null`. |
| `sendLaunchRequest` | L197–244 | Builds launch args by merging optional `launchConfig` over defaults (`scriptPath`, `scriptArgs`, `stopOnEntry`, `justMyCode`). Ensures `noDebug=false` and `console='internalConsole'` if absent. Sanitizes args before logging. |
| `sendAttachRequest` | L249–256 | Forwards `attachConfig` directly as a DAP `attach` request. Sanitizes before logging. |
| `setBreakpoints` | L261–284 | Converts `{line, condition?}[]` to `DebugProtocol.SourceBreakpoint[]`, sets `source.name` via `path.basename`. Returns the full `SetBreakpointsResponse`. |
| `sendConfigurationDone` | L289–293 | Sends DAP `configurationDone` with empty body. |

### Dependencies
- `IDapClient`, `IDapClientFactory`, `ILogger`, `ExtendedInitializeArgs` — from `./dap-proxy-interfaces.js`
- `AdapterPolicy` — type-only from `@debugmcp/shared`
- `sanitizePayloadForLogging` — from `@debugmcp/shared`; called before logging launch/attach args to redact sensitive env vars

### Architectural Notes
- Retry loop uses infinite `for(;;)` with explicit counter and `MAX_CONNECT_ATTEMPTS` guard (L56–78).
- Temporary error handler pattern (L49–52, L63, L71) prevents Node.js from crashing on unhandled `error` events during TCP connection retries.
- `sendLaunchRequest` precedence: `launchConfig` fields override positional parameters; `program` and `args` fall back to positional only when not provided in `launchConfig` (L209–216).
- `disconnect` uses a two-phase teardown: DAP-protocol-level `disconnect` request (with timeout) followed by transport-level `client.disconnect()` (L169–191).
