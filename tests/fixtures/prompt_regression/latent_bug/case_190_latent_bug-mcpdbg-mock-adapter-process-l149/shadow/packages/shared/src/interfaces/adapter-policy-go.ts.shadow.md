# packages\shared\src\interfaces\adapter-policy-go.ts
@source-hash: 2a88fd32d6bd881a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:59Z

## GoAdapterPolicy (L13-338)

Singleton `AdapterPolicy` implementation for the Go Debug Adapter (Delve/dlv). Encodes all Delve-specific behaviors including variable extraction, session lifecycle, stack frame filtering, executable validation, and DAP spawn configuration.

### Primary Responsibility
Implements the `AdapterPolicy` interface for `dlv dap` mode. Consumed by the session manager and proxy infrastructure to customize Go debugging behavior.

---

### Key Properties & Methods

**Identity & Session Strategy (L14-23)**
- `name: 'go'`
- `supportsReverseStartDebugging: false` — no child session support; `buildChildStartArgs` throws
- `childSessionStrategy: 'none'`
- `isChildReadyEvent`: returns `true` when `evt.event === 'initialized'`

**Variable Extraction (L28-77) — `extractLocalVariables`**
- Takes top stack frame, finds `"Locals"` or `"Local"` scope in Delve scopes
- Filters out variables whose names start with `_` (but NOT bare `_`) unless `includeSpecial=true`
- Returns `[]` if no stack frames, no scopes, or no matching local scope

**Scope Names (L82-84) — `getLocalScopeName`**
- Returns `['Locals', 'Arguments']` — Delve's scope naming convention

**Adapter Configuration (L86-90) — `getDapAdapterConfiguration`**
- Returns `{ type: 'dlv-dap' }`

**Executable Resolution (L92-106) — `resolveExecutablePath`**
- Priority: `providedPath` → `process.env.DLV_PATH` → `'dlv'` (default)

**Debugger Configuration (L108-115) — `getDebuggerConfiguration`**
- `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true`

**Session Readiness (L117) — `isSessionReady`**
- Ready only when `state === SessionState.PAUSED`

**Executable Validation (L122-142) — `validateExecutable`**
- Dynamically imports `child_process.spawn` (browser-safe)
- Runs `dlv version`, resolves `true` only if exit code is `0` AND stdout produced output

**Command Queueing (L147-159)**
- `requiresCommandQueueing(): false`
- `shouldQueueCommand()`: always returns `{ shouldQueue: false, shouldDefer: false, reason: 'Go adapter does not queue commands' }`

**State Management (L164-202)**
- `createInitialState()`: `{ initialized: false, configurationDone: false }`
- `updateStateOnCommand`: sets `state.configurationDone = true` when command is `'configurationDone'`
- `updateStateOnEvent`: sets `state.initialized = true` when event is `'initialized'`
- `isInitialized` / `isConnected`: both return `state.initialized`

**Adapter Matching (L207-215) — `matchesAdapter`**
- Returns `true` if `command` contains `'dlv'`, or args contain `'dlv dap'` or `'delve'` (case-insensitive)

**Initialization Behavior (L224-236) — `getInitializationBehavior`**
- `deferConfigDone: false`
- `defaultStopOnEntry: false` — avoids Delve "unknown goroutine 1" bug on entry
- `sendLaunchBeforeConfig: true` — two-phase handling for Delve's `initialized` event timing

**DAP Client Behavior (L241-268) — `getDapClientBehavior`**
- Handles `runInTerminal` reverse requests by acknowledging with empty response
- All child-session-related flags (`mirrorBreakpointsToChild`, `deferParentConfigDone`, `pauseAfterChildAttach`) are `false`
- `childRoutedCommands: undefined`, `normalizeAdapterId: undefined`
- `childInitTimeout: 5000`

**Stack Frame Filtering (L273-302)**
- `filterStackFrames`: removes frames whose `frame.file` contains `/runtime/` or `/testing/` paths (unless `includeInternals=true`)
- `isInternalFrame`: returns `true` for frames with `/runtime/` or `/testing/` in file path

**Spawn Configuration (L307-338) — `getAdapterSpawnConfig`**
- If `payload.adapterCommand` provided: uses it directly (pass-through)
- Otherwise: constructs `dlv dap --listen {host}:{port} --log --log-output dap --log-dest {logDir}` command
- Always returns `mode: 'spawn'`

---

### Notable Architecture Decisions
- Dynamic `import('child_process')` at L124 makes `validateExecutable` safe in browser/edge environments
- `isSessionReady` checks for `SessionState.PAUSED` (not `RUNNING`) — Go/Delve requires a pause before variables can be inspected
- `shouldDeferParentConfigDone` always returns `false` (L17), consistent with `deferParentConfigDone: false` in `getDapClientBehavior`
- No command queueing at all — Delve handles DAP commands synchronously
