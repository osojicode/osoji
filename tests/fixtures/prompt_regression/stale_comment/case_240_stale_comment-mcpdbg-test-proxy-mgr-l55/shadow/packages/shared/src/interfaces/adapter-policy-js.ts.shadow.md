# packages\shared\src\interfaces\adapter-policy-js.ts
@source-hash: 64136a9daaf60a95
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:34Z

## Purpose
Implements `JsDebugAdapterPolicy`, the VS Code js-debug (pwa-node) specific adapter policy that encodes multi-session DAP behavior for JavaScript/TypeScript debugging, conforming to the `AdapterPolicy` interface.

## Key Exports

### `JsAdapterState` interface (L17–21)
Extends `AdapterSpecificState` with JS-specific fields:
- `initializeResponded: boolean` — tracks receipt of initialize response
- `startSent: boolean` — tracks whether launch/attach was sent
- `pendingCommands: Array<{requestId, dapCommand, dapArgs?}>` — queued commands

### `JsDebugAdapterPolicy` constant (L23–759)
A singleton object implementing `AdapterPolicy`. Key methods:

#### Multi-session / child session behavior
- **`buildChildStartArgs`** (L28–39): Constructs `attach` args with `__pendingTargetId` and `continueOnAttach: true` for js-debug child sessions.
- **`isChildReadyEvent`** (L40–44): Signals readiness on `thread` or `stopped` DAP events.
- **`shouldDeferParentConfigDone`** (L27): Always returns `true`.
- **`childSessionStrategy`** (L26): `'launchWithPendingTarget'`.

#### Frame/variable filtering
- **`isInternalFrame`** (L49–53): Detects Node.js internal frames via `<node_internals>` path substring.
- **`filterStackFrames`** (L58–73): Removes internal frames unless `includeInternals=true`; preserves at least one frame.
- **`extractLocalVariables`** (L78–151): Extracts variables from top stack frame, supporting scope names `Local`, `Locals`, `Local:`, `Block:`, `Script`, `Module`, `module`, global. Filters `this`, `__proto__`, `prototype`, V8 internal `[[...]]` names, and debugger internals (`$`, `_$` prefixes) unless `includeSpecial=true`.
- **`getLocalScopeName`** (L156–158): Returns `['Local', 'Locals', 'Local:', 'Block:', 'Script', 'Module', 'module', 'Global']`.

#### DAP handshake (L200–468)
`performHandshake` is the core async method driving the full js-debug initialization sequence:
1. Sends `initialize` with `supportsStartDebuggingRequest: true` (L215–232)
2. Waits (10s timeout) for DAP `initialized` event via `pm.on('dap-event', ...)` (L235–256)
3. Sends `setExceptionBreakpoints` with empty filters (L259–268)
4. Groups and sends `setBreakpoints` per file (L270–293)
5. Sends `configurationDone` (L295–305)
6. **Attach flow** (L335–376): When `req === 'attach'` and port > 0, sends `attach` with `address`, `port`, `continueOnAttach: true`, `attachExistingChildren: true`. Resolves host from `launchConfig.host` → `dapLaunchArgs.host` → `'127.0.0.1'`.
7. **Launch flow** (L379–463): Defaults `program`, `args`, `cwd`, `stopOnEntry`, `justMyCode`, `console='internalConsole'`, `outputCapture='std'`, `smartStep=true`, `pauseForSourceMap=true`, `runtimeExecutable=process.execPath`. Sends `launch` with merged config.

#### Command queueing (L478–524)
`shouldQueueCommand` enforces strict initialization ordering:
- `initialize` → never queued
- Pre-initialize response → all commands queued
- Pre-`initialized` event → config commands queued (`setBreakpoints`, `setFunctionBreakpoints`, etc.)
- `launch`/`attach` before `configurationDone` → deferred (signals `shouldDefer: true`)

`processQueuedCommands` (L529–556): Re-orders queued commands as: config commands → `configurationDone` → `launch`/`attach` → others.

#### State management (L561–619)
- `createInitialState` (L561–569): Returns `JsAdapterState` with all flags `false` and empty `pendingCommands`.
- `updateStateOnCommand` (L574–582): Sets `configurationDone`/`startSent` flags.
- `updateStateOnResponse` (L587–592): Sets `initializeResponded` on `initialize` response.
- `updateStateOnEvent` (L597–603): Sets `initialized` on `initialized` event.
- `isInitialized` (L608–611): Requires both `initialized` AND `initializeResponded`.
- `isConnected` (L616–619): Requires only `initializeResponded`.

#### DAP client behavior (L654–735)
`getDapClientBehavior` returns a `DapClientBehavior` object:
- `handleReverseRequest` (L657–690): Handles `startDebugging` (creates child sessions for `__pendingTargetId`) and `runInTerminal` (acknowledged/no-op). Returns `createChildSession: true` with `childConfig` when pending target not yet adopted.
- `childRoutedCommands` (L693–715): 18 commands routed to child sessions (threads, pause, continue, stepIn/Out, stackTrace, etc.)
- `mirrorBreakpointsToChild: true`, `deferParentConfigDone: true`, `pauseAfterChildAttach: true`, `stackTraceRequiresChild: true`
- `normalizeAdapterId` (L724–728): Maps `'javascript'` → `'pwa-node'`
- `childInitTimeout: 12000` ms

#### Other methods
- `isSessionReady` (L186–187): Ready when `PAUSED`, or `RUNNING` and `stopOnEntry` not set.
- `getAttachBehavior` (L194): `{ pauseAfterAttach: true }`.
- `resolveExecutablePath` (L166–175): Returns provided path or `'node'`.
- `getDebuggerConfiguration` (L177–184): `requiresStrictHandshake: true`, `supportsVariableType: true`.
- `getDapAdapterConfiguration` (L160–163): `{ type: 'pwa-node' }`.
- `matchesAdapter` (L625–636): Matches `js-debug`, `pwa-node`, or `vsdebugserver` in command/args.
- `getInitializationBehavior` (L641–649): `deferConfigDone: true`, `addRuntimeExecutable: true`, `trackInitializeResponse: true`, `requiresInitialStop: true`, `defaultStopOnEntry: false`.
- `getAdapterSpawnConfig` (L740–759): Returns spawn config from `payload.adapterCommand`; returns `undefined` and warns if no adapter command provided.

## Architecture Notes
- Uses `proxyManager as any` pattern (L205) since the interface accepts `unknown`; actual usage expects an `IProxyManager` with `isRunning()`, `sendDapRequest()`, `on()`, `removeListener()`.
- Multi-session: parent session manages `startDebugging` reverse requests; child sessions handle actual thread/stack operations.
- `continueOnAttach: true` is required by js-debug for attach flow; child sessions also use it.
- The `getAttachBehavior: () => ({ pauseAfterAttach: true })` comment references issue #124 — js-debug continues on attach, so an explicit pause must follow.
- Attach host resolution (L339–344) was changed from hardcoded `127.0.0.1` to support non-loopback targets (issue #124).
- `attachSimplePort` is intentionally NOT set alongside `port` to avoid double-attach conflict (L345–350, issue #124).
- `path` module is imported but only used in `performHandshake` for `path.dirname(scriptPath)` (L393).

## Dependencies
- `@vscode/debugprotocol`: `DebugProtocol` types
- `path`: Node.js path utilities
- `./adapter-policy.js`: `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` interfaces
- `@debugmcp/shared`: `SessionState` enum
- `../models/index.js`: `StackFrame`, `Variable` types
- `./dap-client-behavior.js`: `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult` interfaces
