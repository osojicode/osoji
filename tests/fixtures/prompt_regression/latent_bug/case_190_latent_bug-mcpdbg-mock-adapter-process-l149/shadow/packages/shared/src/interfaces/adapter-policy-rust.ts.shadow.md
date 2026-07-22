# packages\shared\src\interfaces\adapter-policy-rust.ts
@source-hash: ff5c359907da5ac2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:26Z

## RustAdapterPolicy (L13–321)

Implements `AdapterPolicy` for the Rust Debug Adapter (CodeLLDB / `lldb`). This is a singleton policy object — not a class — exported as a named constant. All methods are plain functions assigned to object properties.

### Primary Responsibility
Encodes all CodeLLDB-specific behaviors: variable extraction, adapter spawning, DAP client configuration, command queueing decisions, and state lifecycle management.

---

### Key Properties & Methods

**Identity / Metadata**
- `name: 'rust'` (L14) — policy discriminant name
- `supportsReverseStartDebugging: false` (L15) — CodeLLDB does not support reverse debugging
- `childSessionStrategy: 'none'` (L16) — no child sessions; `buildChildStartArgs` always throws

**Variable Extraction**
- `extractLocalVariables` (L28–78): Reads `stackFrames[0]`, locates the "Local"/"Locals" scope, returns variables from `variables[localScope.variablesReference]`. Filters out LLDB-internal names (prefix `$`, `__`, `_lldb`, `_debug`) unless `includeSpecial=true`.
- `getLocalScopeName` (L83–85): Returns `['Local', 'Locals']` — CodeLLDB scope naming convention.

**Adapter Configuration**
- `getDapAdapterConfiguration` (L87–91): Returns `{ type: 'lldb' }`.
- `getDebuggerConfiguration` (L103–112): Returns capability flags — `supportsVariableType`, `supportsValueFormat`, `supportsMemoryReferences` all `true`; `requiresStrictHandshake` and `skipConfigurationDone` both `false`.
- `getInitializationBehavior` (L227–229): Returns `{}` — no special initialization quirks.

**Executable Resolution**
- `resolveExecutablePath` (L93–101): Returns `providedPath` if given; otherwise returns `undefined` (defers to `codelldb-resolver.ts` which checks `CODELLDB_PATH` env var).
- `validateExecutable` (L119–148): Async. Dynamically imports `fs/promises` and `child_process`. Checks file existence via `fs.access`, then spawns `codelldb --version`, resolves `true` only if exit code is 0 AND stdout includes the string `'codelldb'`.

**Spawn Configuration**
- `getAdapterSpawnConfig` (L266–320): Resolves the CodeLLDB binary path using platform/arch matrix (`win32-x64`, `win32-arm64`, `darwin-x64`, `darwin-arm64`, `linux-x64`, `linux-arm64`). Vendor path: `packages/adapter-rust/vendor/codelldb/<platformDir>/adapter/codelldb[.exe]`. Spawns with `--port <adapterPort>`. On `win32`, sets `LLDB_USE_NATIVE_PDB_READER=1`. Throws on unsupported platforms. If `payload.adapterCommand` is provided, bypasses vendor path entirely and uses custom command.

**Session State**
- `isSessionReady` (L114): Returns `true` iff `state === SessionState.PAUSED`.
- `createInitialState` (L170–175): Returns `{ initialized: false, configurationDone: false }`.
- `updateStateOnCommand` (L180–184): Sets `state.configurationDone = true` when command is `'configurationDone'`.
- `updateStateOnEvent` (L189–193): Sets `state.initialized = true` when event is `'initialized'`.
- `isInitialized` (L198–200): Returns `state.initialized`.
- `isConnected` (L205–208): Returns `state.initialized` (connected ≡ initialized).

**Command Queueing**
- `requiresCommandQueueing` (L153): Always returns `false`.
- `shouldQueueCommand` (L158–165): Always returns `{ shouldQueue: false, shouldDefer: false, reason: '...' }`.

**Adapter Matching**
- `matchesAdapter` (L213–222): Detects CodeLLDB by checking `command` or joined `args` (lowercased) for `'codelldb'`, `'lldb-server'`, or `'lldb'`.

**Child Session / Reverse Requests**
- `shouldDeferParentConfigDone` (L17): Always returns `false`.
- `isChildReadyEvent` (L21–23): Returns `true` if `evt.event === 'initialized'` (unused in practice since `childSessionStrategy: 'none'`).
- `getDapClientBehavior` (L234–261): Returns a `DapClientBehavior` object. Only handles `runInTerminal` reverse requests (acknowledges with empty response). All child-session flags are `false`/`undefined`. `childInitTimeout: 5000`.

---

### Dependencies
- `@vscode/debugprotocol` — `DebugProtocol.Event`, `DebugProtocol.Request`, `DebugProtocol.Scope`
- `path` (Node.js) — used in `getAdapterSpawnConfig` for vendored binary path resolution
- `./adapter-policy` — `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` interfaces
- `@debugmcp/shared` — `SessionState` enum (specifically `SessionState.PAUSED`)
- `../models/index` — `StackFrame`, `Variable` model types
- `./dap-client-behavior` — `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult`

---

### Architectural Notes
- **Dynamic imports** (`fs/promises`, `child_process`) in `validateExecutable` prevent browser-environment breakage.
- **Vendor path** is hardcoded relative to `process.cwd()` — assumes execution from monorepo root.
- **No child session support**: `buildChildStartArgs` always throws; `childSessionStrategy: 'none'` communicates this to the framework.
- `matchesAdapter` uses broad `'lldb'` substring match which may produce false positives if other adapters pass LLDB-related args.