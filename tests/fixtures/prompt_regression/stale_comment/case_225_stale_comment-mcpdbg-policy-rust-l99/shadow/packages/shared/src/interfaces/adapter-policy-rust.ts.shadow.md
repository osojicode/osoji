# packages\shared\src\interfaces\adapter-policy-rust.ts
@source-hash: ff5c359907da5ac2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:59Z

## Purpose
Defines `RustAdapterPolicy`, a concrete implementation of the `AdapterPolicy` interface for the CodeLLDB debug adapter used with Rust. Encodes all CodeLLDB-specific behaviors: variable extraction, scope naming, spawn configuration, command handling, and DAP client behavior.

## Key Export

### `RustAdapterPolicy` (L13–321)
A singleton object literal implementing `AdapterPolicy`. Key method groups:

**Identity & Session Strategy (L14–23)**
- `name: 'rust'`
- `supportsReverseStartDebugging: false` — no child session support
- `childSessionStrategy: 'none'`
- `shouldDeferParentConfigDone`: always returns `false`
- `buildChildStartArgs`: throws unconditionally (child sessions unsupported)
- `isChildReadyEvent`: returns `true` if `evt.event === 'initialized'`

**Variable Extraction (L28–78) — `extractLocalVariables`**
- Takes `stackFrames`, `scopes` map, `variables` map, `includeSpecial` (default `false`)
- Uses `stackFrames[0]` (top frame)
- Looks up scopes keyed by `topFrame.id`, finds scope named `'Local'` or `'Locals'`
- Looks up variables keyed by `localScope.variablesReference`
- Filters out variables whose names start with `$`, `__`, `_lldb`, or `_debug` unless `includeSpecial=true`

**Scope Naming (L83–85) — `getLocalScopeName`**
- Returns `['Local', 'Locals']` — CodeLLDB scope name variants

**Adapter Configuration (L87–91) — `getDapAdapterConfiguration`**
- Returns `{ type: 'lldb' }`

**Executable Resolution (L93–101) — `resolveExecutablePath`**
- Returns `providedPath` if provided, otherwise `undefined` (defers to `codelldb-resolver.ts`)

**Debugger Configuration (L103–112) — `getDebuggerConfiguration`**
- `requiresStrictHandshake: false`, `skipConfigurationDone: false`
- `supportsVariableType: true`, `supportsValueFormat: true`, `supportsMemoryReferences: true`

**Session Readiness (L114) — `isSessionReady`**
- Returns `true` when `state === SessionState.PAUSED`

**Executable Validation (L119–148) — `validateExecutable`** (async)
- Dynamically imports `fs/promises` and `child_process`
- Checks file existence via `fs.access(..., F_OK)`
- Spawns `codelldbPath --version`, resolves `true` if exit code 0 AND stdout includes `'codelldb'`
- Returns `false` on any error/exception

**Command Handling (L153–165)**
- `requiresCommandQueueing`: always `false`
- `shouldQueueCommand`: returns `{ shouldQueue: false, shouldDefer: false, reason: '...' }`

**State Management (L170–208)**
- `createInitialState`: returns `{ initialized: false, configurationDone: false }`
- `updateStateOnCommand`: sets `state.configurationDone = true` when `command === 'configurationDone'`
- `updateStateOnEvent`: sets `state.initialized = true` when `event === 'initialized'`
- `isInitialized`: returns `state.initialized`
- `isConnected`: returns `state.initialized` (connected = initialized for Rust adapter)

**Adapter Matching (L213–222) — `matchesAdapter`**
- Checks if adapter command or args (lowercased) include `'codelldb'`, `'lldb-server'`, or `'lldb'`

**Initialization Behavior (L227–229) — `getInitializationBehavior`**
- Returns `{}` — no special quirks

**DAP Client Behavior (L234–261) — `getDapClientBehavior`**
- `handleReverseRequest`: handles `runInTerminal` by sending empty response; all others return `{ handled: false }`
- `childRoutedCommands: undefined`, `mirrorBreakpointsToChild: false`, `deferParentConfigDone: false`, `pauseAfterChildAttach: false`
- `normalizeAdapterId: undefined`
- `childInitTimeout: 5000`, `suppressPostAttachConfigDone: false`

**Spawn Configuration (L266–320) — `getAdapterSpawnConfig`**
- Parameters: `payload`, `platform` (default `process.platform`), `arch` (default `process.arch`)
- If `payload.adapterCommand` is set → returns spawn config using that command directly (L268–278)
- Otherwise → resolves vendored CodeLLDB path from `packages/adapter-rust/vendor/codelldb/<platformDir>/adapter/codelldb[.exe]` (L281–302)
- Platform mapping: `win32`/`darwin`/`linux` × `arm64`/`x64`; throws on unsupported platform
- Spawn args: `['--port', String(payload.adapterPort)]`
- On Windows: injects `LLDB_USE_NATIVE_PDB_READER: '1'` into env (L317)
- Returns mode `'spawn'` with `host`, `port`, `logDir` from payload

## Dependencies
- `@vscode/debugprotocol` — `DebugProtocol` types
- `path` — path resolution for vendored CodeLLDB binary
- `./adapter-policy.js` — `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` interfaces
- `@debugmcp/shared` — `SessionState` enum
- `../models/index.js` — `StackFrame`, `Variable` types
- `./dap-client-behavior.js` — `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult`
- Dynamic: `fs/promises`, `child_process` (in `validateExecutable`)

## Architecture Notes
- Follows policy pattern: all adapter-specific logic is isolated in this object, consumed by adapter-agnostic session management code
- Vendored binary path is relative to `process.cwd()` (assumed project root), which is brittle if CWD changes
- `matchesAdapter` uses broad string matching on `'lldb'` which could match non-CodeLLDB LLDB-based adapters
