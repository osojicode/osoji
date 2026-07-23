# src\proxy\dap-proxy-connection-manager.ts
@source-hash: 1d69bccf356607b0
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:48Z

## DapConnectionManager (L16–294)

Central class managing the lifecycle of a Debug Adapter Protocol (DAP) connection: connection establishment with retry, session initialization, event handler registration, launch/attach request dispatch, breakpoint setting, and graceful disconnect.

### Class: `DapConnectionManager` (L16–294)

Injected dependencies via constructor (L24–27):
- `dapClientFactory: IDapClientFactory` — creates `IDapClient` instances, optionally with an `AdapterPolicy`
- `logger: ILogger` — structured logging throughout

Private constants (L19–21):
- `INITIAL_CONNECT_DELAY = 500` ms — wait before first connect attempt (helps debugpy startup)
- `MAX_CONNECT_ATTEMPTS = 60` — maximum retry count before throwing
- `CONNECT_RETRY_INTERVAL = 200` ms — delay between retries

Optional state:
- `policy?: AdapterPolicy` (L22) — set via `setAdapterPolicy()` (L32–34); forwarded to factory during `connectWithRetry`

---

### Key Methods

#### `setAdapterPolicy(policy)` (L32–34)
Stores an `AdapterPolicy` for use when creating DAP clients. Must be called before `connectWithRetry` if policy enforcement is needed.

#### `connectWithRetry(host, port)` (L39–79)
1. Waits `INITIAL_CONNECT_DELAY` ms.
2. Creates `IDapClient` via factory (with or without policy).
3. Attaches a temporary `error` event handler to prevent unhandled-event crashes during retry loop.
4. Loops up to `MAX_CONNECT_ATTEMPTS` times, calling `client.connect()`, retrying every `CONNECT_RETRY_INTERVAL` ms.
5. On success: removes temp handler, returns connected `IDapClient`.
6. On exhaustion: removes temp handler, throws `Error`.

#### `initializeSession(client, sessionId, adapterId?)` (L84–100)
Sends DAP `initialize` request with hardcoded MCP-specific args. `adapterId` defaults to `'python'`. `clientID` is `mcp-proxy-${sessionId}`.

#### `setupEventHandlers(client, handlers)` (L105–156)
Registers optional callbacks for DAP events: `initialized`, `output`, `stopped`, `continued`, `thread`, `exited`, `terminated`, `error`, `close`. Each handler is only registered if provided (non-null check guards).

#### `disconnect(client, terminateDebuggee?)` (L161–192)
- If `client` is `null`, logs and returns.
- Sends DAP `disconnect` request with a 1000 ms timeout via `Promise.race`.
- Always calls `client.disconnect()` for final cleanup, regardless of whether the request succeeded/timed-out.

#### `sendLaunchRequest(client, scriptPath, scriptArgs?, stopOnEntry?, justMyCode?, launchConfig?)` (L197–244)
Merges `launchConfig` overrides with defaults. Priority: `launchConfig` fields > method parameters. Sets defaults for `noDebug = false` (L233) and `console = 'internalConsole'` (L237) if not present. Logs sanitized payload via `sanitizePayloadForLogging`.

#### `sendAttachRequest(client, attachConfig)` (L249–256)
Sends DAP `attach` request directly with the provided config (no merging). Logs sanitized payload.

#### `setBreakpoints(client, sourcePath, breakpoints)` (L261–284)
Constructs `SetBreakpointsArguments` using `path.basename` for source name. Returns `DebugProtocol.SetBreakpointsResponse`.

#### `sendConfigurationDone(client)` (L289–293)
Sends DAP `configurationDone` request with empty args.

---

### Dependencies
- `path` (Node stdlib) — `path.basename` in `setBreakpoints`
- `@vscode/debugprotocol` — DAP types (`DebugProtocol.*`)
- `./dap-proxy-interfaces` — `IDapClient`, `IDapClientFactory`, `ILogger`, `ExtendedInitializeArgs`
- `@debugmcp/shared` — `AdapterPolicy` (type), `sanitizePayloadForLogging` (utility)

### Architectural Notes
- All DAP request names (`'initialize'`, `'launch'`, `'attach'`, `'setBreakpoints'`, `'configurationDone'`, `'disconnect'`) are passed as string literals to `client.sendRequest`.
- The class is stateless beyond `policy` and injected dependencies; the caller owns and passes the `IDapClient` instance to most methods.
- Error handling is defensive: disconnect always attempts cleanup even after timeout.