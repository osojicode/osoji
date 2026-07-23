# packages\adapter-ruby\src\ruby-debug-adapter.ts
@source-hash: 01cb2af9a442e08f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:46Z

## RubyDebugAdapter

Primary adapter implementation for Ruby debugging via `rdbg` (Ruby debug gem). Implements `IDebugAdapter` and extends `EventEmitter` to bridge the generic debug adapter interface with Ruby-specific tooling.

### Class: `RubyDebugAdapter` (L70–606)
Implements `IDebugAdapter` from `@debugmcp/shared`. Manages state transitions, environment validation, path resolution with TTL caching, DAP event/response handling, and config transformation for both launch and attach scenarios.

**Key fields:**
- `language = DebugLanguage.RUBY` (L71) — language discriminant
- `state: AdapterState` (L74) — internal FSM state, transitions via `transitionTo()`
- `rubyPathCache / rdbgPathCache: Map<string, RubyPathCacheEntry>` (L76–77) — 60-second TTL caches for resolved executable paths
- `cacheTimeout = 60000` (L78) — TTL in ms
- `currentThreadId: number | null` (L79) — tracks last stopped thread
- `connected: boolean` (L80) — tracks DAP connection state

### State Machine
`transitionTo(newState)` (L131–135) updates `this.state` and emits `'stateChanged'` with old/new state pair.

State flow:
- `initialize()` (L87–106): UNINITIALIZED → INITIALIZING → READY (or ERROR on validation failure)
- `connect()` (L435–439): → CONNECTED
- `handleDapEvent('stopped'|'continued')` (L412–430): → DEBUGGING
- `handleDapEvent('terminated')`: → DISCONNECTED
- `disconnect()` (L441–446): → DISCONNECTED
- `dispose()` (L108–115): → UNINITIALIZED, clears caches

`isReady()` (L121–125) returns true for READY, CONNECTED, or DEBUGGING states.

### Environment Validation: `validateEnvironment()` (L137–190)
1. Resolves Ruby executable via `resolveExecutablePath()` → calls `findRubyExecutable()`
2. Checks Ruby version ≥ 2.7; emits `RUBY_VERSION_TOO_OLD` error if not
3. Resolves rdbg via `resolveRdbgPath()` → calls `findRdbgExecutable()`
4. Returns `ValidationResult { valid, errors, warnings }`

### Path Resolution (cached)
- `resolveExecutablePath(preferredPath?)` (L209–224): public, uses `rubyPathCache`, delegates to `findRubyExecutable()`
- `resolveRdbgPath(preferredPath?)` (L544–558): private, uses `rdbgPathCache`, delegates to `findRdbgExecutable()`
- `getCachedRdbgPath()` (L561–563): private synchronous accessor for cached rdbg `'default'` entry

### Command Building: `buildAdapterCommand(config)` (L234–267)
Constructs the rdbg launch invocation:
1. Gets rdbg path from cache, `RDBG_PATH` env var, or platform default (`rdbg.bat` / `rdbg`)
2. Builds `--open --host <host> --port <port> -c -- <target>` args
3. Uses `buildRdbgInvocation()` from ruby-utils
4. Sets `RUBY_DEBUG_DAP_SHOW_PROTOCOL` env var based on `DEBUG` env
5. Optionally prepends `bundle exec` via `buildTargetCommand()` if `useBundler` is set

### Config Transformation
- `transformLaunchConfig(config)` (L295–335): Maps generic `program`/`script` field → `script`; sets `type:'rdbg'`, `request:'launch'`, `localfs:true` by default; handles `command`, `localfsMap`, `bundlePath`, `useBundler`
- `transformAttachConfig(config)` (L358–394): Requires `port: number`; throws `AdapterError(ENVIRONMENT_INVALID)` if missing; sets `localfs` via `isLocalHost()` check
- `getDefaultLaunchConfig()` (L337–344): `stopOnEntry:false, justMyCode:true, env:{}, cwd:process.cwd()`
- `getDefaultAttachConfig()` (L396–403): `request:'attach', host:'127.0.0.1', stopOnEntry:true, justMyCode:true`

### DAP Event Handling: `handleDapEvent(event)` (L412–430)
Switch on `event.event`:
- `'stopped'` → DEBUGGING state, captures `threadId`
- `'continued'` → DEBUGGING state
- `'terminated'` → DISCONNECTED state
All events re-emitted via `this.emit(event.event, event.body)`.

### Capabilities: `getCapabilities()` (L523–542)
Reports: `configurationDone`, function/conditional/hit-conditional breakpoints, evaluate-for-hovers, completions, terminate, `supportTerminateDebuggee`. Exception breakpoint filter: `'any'` (Rescue any exception).

### Feature Support: `supportsFeature(feature)` (L492–502)
Supports: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `TERMINATE_REQUEST`.

### Notable Architectural Decisions
- `sendDapRequest()` (L405–410) is a stub returning `{} as T` — DAP communication is handled by a higher-level proxy layer, not this adapter directly
- `handleDapResponse()` (L432–433) is a no-op stub
- `usesDirectConnectForAttach()` returns `true` (L354–356) — attach mode bypasses adapter subprocess spawning
- Comments at L240–246 explain why `--nonstop` is intentionally omitted and why `--open` (not `--open=vscode`) is used
- Path caches keyed by `preferredPath || 'default'`; version also stored in cache entries to avoid redundant subprocess calls

### Internal Interfaces
- `RubyPathCacheEntry` (L34–38): `{ path, timestamp, version? }`
- `RubyLaunchConfig` (L40–54): extends `LanguageSpecificLaunchConfig`, adds rdbg-specific fields
- `RubyAttachConfig` (L56–68): extends `LanguageSpecificAttachConfig`, required `type:'rdbg'`, `request:'attach'`, `host`, `port`, `localfs`

### Dependencies
- `@debugmcp/shared`: Core interfaces, enums, error types
- `./utils/ruby-utils.js`: `findRubyExecutable`, `findRdbgExecutable`, `getRubyVersion`, `getRdbgVersion`, `getRubySearchPaths`, `buildRdbgInvocation`
- `@vscode/debugprotocol`: DAP protocol types
- `events`: Node.js `EventEmitter`