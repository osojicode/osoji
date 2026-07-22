# packages\shared\src\interfaces\adapter-policy-js.ts
@source-hash: 7b9e3696271f5ebb
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:56Z

## Purpose
Defines the `JsDebugAdapterPolicy` — a concrete implementation of the `AdapterPolicy` interface tailored for VS Code's js-debug (pwa-node) adapter. Encodes JavaScript/Node.js-specific multi-session DAP behaviors, command sequencing, breakpoint handling, session state management, and spawn configuration.

## Key Exports

### `JsAdapterState` interface (L16-20)
Extends `AdapterSpecificState` with JS-specific fields:
- `initializeResponded: boolean` — tracks when `initialize` response has been received
- `startSent: boolean` — tracks when `launch`/`attach` command was sent
- `pendingCommands: Array<{requestId, dapCommand, dapArgs?}>` — queued commands awaiting dispatch

### `JsDebugAdapterPolicy` constant (L22-760)
Implements `AdapterPolicy` with the following notable methods:

**Identity/Metadata:**
- `name: 'js-debug'` (L23)
- `supportsReverseStartDebugging: true` (L24) — enables parent-child multi-session via `startDebugging` reverse requests
- `childSessionStrategy: 'launchWithPendingTarget'` (L25)

**Multi-session lifecycle:**
- `buildChildStartArgs(pendingId, parentConfig)` (L27-38): Builds attach args with `__pendingTargetId` and `continueOnAttach: true`
- `isChildReadyEvent(evt)` (L39-43): Considers child ready on `thread` or `stopped` DAP events
- `shouldDeferParentConfigDone()` (L26): Always returns `true`

**Stack frame / variable inspection:**
- `isInternalFrame(frame)` (L48-52): Identifies Node.js internal frames by `<node_internals>` in path
- `filterStackFrames(frames, includeInternals)` (L57-72): Filters internal frames; preserves at least 1 frame as fallback
- `extractLocalVariables(stackFrames, scopes, variables, includeSpecial)` (L77-150): Resolves Local/Block/Script/Module scope from top frame; filters `this`, `__proto__`, `prototype`, `[[...]]`, `$`/`_$` prefixed names
- `getLocalScopeName()` (L155-157): Returns `['Local', 'Locals', 'Local:', 'Block:', 'Script', 'Module', 'module', 'Global']`

**Adapter configuration:**
- `getDapAdapterConfiguration()` (L159-163): Returns `{ type: 'pwa-node' }`
- `resolveExecutablePath(providedPath?)` (L165-174): Returns provided path or `'node'`
- `getDebuggerConfiguration()` (L176-183): Returns `requiresStrictHandshake: true`, `supportsVariableType: true`

**Session readiness:**
- `isSessionReady(state, options)` (L185-186): Ready when `PAUSED` or (`!stopOnEntry` and `RUNNING`)
- `getAttachBehavior()` (L193): Returns `{ pauseAfterAttach: true }` — required because `continueOnAttach` keeps target running

**DAP handshake (`performHandshake`)** (L199-469): Async method implementing strict js-debug initialization sequence:
1. Send `initialize` with `supportsStartDebuggingRequest: true` (L214-231)
2. Wait for `initialized` DAP event (10s timeout) (L234-255)
3. Send `setExceptionBreakpoints` with empty filters (L258-267)
4. Send `setBreakpoints` grouped by file (L269-292)
5. Send `configurationDone` (L294-304)
6. Branch on `req === 'attach'` with a valid `attachPort` (L334): sends `attach` with `port`, `address`, `continueOnAttach: true`, `attachExistingChildren: true`, optional `stopOnEntry`
7. Otherwise (LAUNCH flow, L376-464): Sets defaults for `program`, `args`, `cwd`, `stopOnEntry`, `justMyCode`, `console: 'internalConsole'`, `outputCapture: 'std'`, `smartStep: true`, `pauseForSourceMap: true`, `runtimeExecutable: process.execPath`; resolves `sourceMaps`, `outFiles`, `resolveSourceMapLocations`

**Command queueing:**
- `requiresCommandQueueing()` (L474): Always returns `true`
- `shouldQueueCommand(command, state)` (L479-525): 
  - `initialize` → never queue
  - Before `initializeResponded` → queue all
  - Config commands (`setBreakpoints`, etc.) before `initialized` event → queue
  - `launch`/`attach` before `configurationDone` → queue+defer
- `processQueuedCommands(commands)` (L530-557): Reorders to strict sequence: configs → configurationDone → launches/attaches → others

**State management:**
- `createInitialState()` (L562-570): Returns `JsAdapterState` with all flags `false`
- `updateStateOnCommand(command, _args, state)` (L575-583): Sets `configurationDone` and `startSent` flags
- `updateStateOnResponse(command, _response, state)` (L588-593): Sets `initializeResponded` on `initialize` response
- `updateStateOnEvent(event, _body, state)` (L598-604): Sets `initialized` on `initialized` event
- `isInitialized(state)` (L609-612): `initialized && initializeResponded`
- `isConnected(state)` (L617-621): `initializeResponded`

**Adapter matching:**
- `matchesAdapter(adapterCommand)` (L626-637): Matches `js-debug`, `pwa-node`, or `vsdebugserver` in command or args

**Initialization behavior:**
- `getInitializationBehavior()` (L642-650): `deferConfigDone: true`, `addRuntimeExecutable: true`, `trackInitializeResponse: true`, `requiresInitialStop: true`, `defaultStopOnEntry: false`

**DAP client behavior (`getDapClientBehavior`)** (L655-736):
- `handleReverseRequest`: Handles `startDebugging` (creates child session with `__pendingTargetId` dedup via `adoptedTargets`) and `runInTerminal` (ack without spawning)
- `childRoutedCommands`: Set of 19 DAP commands routed to child sessions (threads, pause, continue, stepIn/Out, stackTrace, scopes, variables, evaluate, etc.)
- `mirrorBreakpointsToChild: true`, `deferParentConfigDone: true`, `pauseAfterChildAttach: true`, `stackTraceRequiresChild: true`
- `normalizeAdapterId`: Maps `'javascript'` → `'pwa-node'`
- `childInitTimeout: 12000`

**Spawn config:**
- `getAdapterSpawnConfig(payload)` (L741-760): Returns spawn config from `payload.adapterCommand`; returns `undefined` with warning if no command provided

## Architecture Notes
- Uses `as any` cast for `proxyManager` in `performHandshake` to avoid circular DI issues (L204); relies on duck-typed `pm.isRunning()`, `pm.sendDapRequest()`, `pm.on()`, `pm.removeListener()`
- `JsAdapterState` extends `AdapterSpecificState`, which carries `initialized` and `configurationDone` base fields — `shouldQueueCommand` accesses both the base and extended fields
- `filterStackFrames` references `JsDebugAdapterPolicy.isInternalFrame` by name (L64) — direct self-reference on the policy object
- Dynamic import of `'path'` in `performHandshake` (L380) to avoid circular dependency issues at module load time
- `continueOnAttach: true` is critical for js-debug to work properly in multi-session mode (L35, L355)
- Issue #124 pattern: avoid setting both `attachSimplePort` and `port` together as it causes double-attach race (L344-349)