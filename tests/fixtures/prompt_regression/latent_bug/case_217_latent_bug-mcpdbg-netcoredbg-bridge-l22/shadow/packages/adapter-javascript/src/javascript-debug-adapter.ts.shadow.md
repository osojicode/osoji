# packages\adapter-javascript\src\javascript-debug-adapter.ts
@source-hash: f636372ac1218d61
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:58Z

## JavascriptDebugAdapter (L35–795)

Primary debug adapter implementation for JavaScript/TypeScript debugging via the vendored `js-debug` (vscode's pwa-node) adapter. Implements `IDebugAdapter` from `@debugmcp/shared` and extends `EventEmitter`.

### Primary Responsibilities
- Lifecycle management: initialize → ready → connected → debugging → disconnected (L55–110)
- Environment validation: checks for vendored `vsDebugServer.cjs/.js` in multiple search paths (L145–193)
- Building the adapter spawn command with TCP port, host, env, and `--max-old-space-size` (L238–325)
- Transforming generic launch/attach configs into `pwa-node`-specific DAP configs (L337–594)
- TypeScript runtime detection (tsx > ts-node > node) and runtime args injection (L436–530)
- DAP event handling: updates thread ID on `stopped`, transitions state, emits normalized events (L610–648)
- Feature/capability declarations for js-debug (L710–757)

### Key Class: `JavascriptDebugAdapter` (L35–795)
- `language`: `'javascript'` cast to `DebugLanguage` (L36)
- `name`: `'JavaScript/TypeScript Debug Adapter'` (L37)
- `state`: `AdapterState` internal FSM field (L39)
- `cachedNodePath`: per-instance memoized node executable path (L46)

### Lifecycle Methods
- `initialize()` (L55–90): validates environment, transitions state to READY, emits `'initialized'`
- `dispose()` (L92–110): clears runtime state, emits `'disconnected'` if was connected, emits `'disposed'`
- `transitionTo(next)` (L137–141): internal FSM helper, emits `'stateChanged'`

### State Methods
- `getState()` (L114): returns current `AdapterState`
- `isReady()` (L118–124): true when state is READY, CONNECTED, or DEBUGGING
- `getCurrentThreadId()` (L126–128): returns last `threadId` from DAP `stopped` event
- `createLaunchBarrier(command)` (L130–135): returns `JsDebugLaunchBarrier` only for `'launch'` command

### Environment & Executable
- `validateEnvironment()` (L145–193): async; checks 4 possible paths for vendored `vsDebugServer.cjs/.js`; pushes `JS_DEBUG_NOT_FOUND` error if none exist
- `getRequiredDependencies()` (L195–204): returns Node.js dependency info
- `resolveExecutablePath(preferredPath?)` (L208–225): memoized `findNode()` call; overrides cache if `preferredPath` given
- `getDefaultExecutableName()` (L227–229): `'node'`
- `getExecutableSearchPaths()` (L231–234): splits `process.env.PATH` by `path.delimiter`

### Adapter Command Building: `buildAdapterCommand(config)` (L238–325)
- Searches 6 paths for `vsDebugServer.cjs/.js` (including container absolute paths)
- Throws `AdapterError(ENVIRONMENT_INVALID)` if not found or port is 0/undefined
- Spawns: `[node, adapterPath, String(port), host]`
- Injects `--max-old-space-size=4096` into `NODE_OPTIONS` if not already set

### Launch Config Transformation: `transformLaunchConfig(config)` (L337–533)
- Produces `type: 'pwa-node'`, `request: 'launch'` config
- Detects TypeScript by extension regex `/\.([mc])?tsx?$/i` (L366)
- Runtime priority: explicit override → tsx (detected via `detectBinary`) → `process.execPath`
- Injects ts-node require hooks (`-r ts-node/register`, `-r ts-node/register/transpile-only`) when ts-node detected and not using tsx (L466–490)
- Adds `--loader ts-node/esm` for ESM projects (L476–479)
- Adds `-r tsconfig-paths/register` when tsconfig paths present (L483–486)
- Normalizes and deduplicates runtime args (L494)
- Inspector flag handling: promotes bare `--inspect`/`--inspect-brk` to `--inspect-brk=9229`; adds `--inspect-brk=9229` when `stopOnEntry=true` (L504–530)
- `cwd` fallback: `MCP_WORKSPACE_ROOT` env var in container mode, else `process.cwd()` (L351–358)

### Attach Config: `transformAttachConfig(config)` (L574–594)
- Produces `type: 'pwa-node'`, `request: 'attach'` config with host/port passthrough

### DAP Protocol
- `handleDapEvent(event)` (L610–648): handles `output`, `stopped` (updates thread ID, transitions to DEBUGGING), `continued`, `terminated`/`exited`; emits event body on EventEmitter
- `sendDapRequest()` (L605–608): stub returning empty object — transport handled by ProxyManager
- `handleDapResponse()` (L650–652): no-op

### Connection
- `connect(host, port)` (L656–662): sets `connected=true`, transitions to CONNECTED, emits `'connected'`
- `disconnect()` (L664–670): sets `connected=false`, clears threadId, transitions to DISCONNECTED

### Private Helpers
- `normalizeBinary(value?)` (L536–545): normalizes path to lowercase forward-slash form
- `isNodeRuntime(executable?)` (L547–551): checks basename is `node`, `node.exe`, or `node.cmd`
- `normalizeAndDedupeArgs(args)` (L759–787): deduplicates `-r <module>` and `--loader <ld>` pairs
- `hasPairArgs(args, flag, value)` (L789–794): checks if flag+value pair already exists in args array

### Supported Features (L710–724)
`CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `SET_VARIABLE`, `LOG_POINTS`, `EXCEPTION_INFO_REQUEST`, `LOADED_SOURCES_REQUEST`

### Events Emitted
- `'initialized'`, `'disposed'`, `'connected'`, `'disconnected'`, `'stateChanged'` — lifecycle
- DAP event names (e.g., `'stopped'`, `'output'`, `'terminated'`) — forwarded DAP events

### Notable Architectural Decisions
- Uses vendored `js-debug` (not npm-installed) — must be built with `pnpm -w -F @debugmcp/adapter-javascript run build:adapter`
- TCP transport is mandatory; port 0 or undefined throws immediately
- `sendDapRequest` and `handleDapResponse` are stubs — actual DAP transport delegated to ProxyManager
- `language` field uses `as unknown as DebugLanguage` cast (L36) because the string `'javascript'` may not directly satisfy the `DebugLanguage` enum type
- Container-mode awareness via `MCP_CONTAINER` and `MCP_WORKSPACE_ROOT` env vars