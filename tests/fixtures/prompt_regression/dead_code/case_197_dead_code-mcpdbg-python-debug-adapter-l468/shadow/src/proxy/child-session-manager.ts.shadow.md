# src\proxy\child-session-manager.ts
@source-hash: edf3ef614abff7bf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## ChildSessionManager

Manages child DAP (Debug Adapter Protocol) debug sessions for multi-session adapters, particularly JavaScript debugging with js-debug/pwa-node which spawns multiple concurrent sessions. Extends `EventEmitter` to propagate child session lifecycle events to consumers.

### Architecture

The manager acts as a lifecycle controller for child `MinimalDapClient` instances. When a parent adapter signals a new pending target, `createChildSession` orchestrates the full handshake: connect → initialize → configure (breakpoints/exception filters) → attach → post-attach init → optional pause. A `createChildSafePolicy` wrapper prevents infinite recursion by stripping reverse-debugging capabilities from child policies (no grandchildren).

### Key Classes & Functions

**`createInstanceId()` (L20-22):** Internal — generates a 4-byte hex ID for log correlation.

**`createChildSafePolicy(policy)` (L24-59):** Internal — creates a modified `AdapterPolicy` that disables `supportsReverseStartDebugging`, sets `childSessionStrategy: 'none'`, and overrides `getDapClientBehavior()` to strip child-routing fields and short-circuit `handleReverseRequest` so child adapters do not spawn grandchildren.

**`ChildSessionOptions` interface (L61-65):** Constructor input — `policy: AdapterPolicy`, `host: string`, `port: number`.

**`ChildSessionManager` class (L67-501):** Core export. Key state:
- `adoptedTargets: Set<string>` (L74) — pendingIds already processed; prevents double-adoption
- `childSessions: Map<string, MinimalDapClient>` (L75) — active child clients keyed by pendingId
- `activeChild: MinimalDapClient | null` (L76) — currently active child for command routing
- `storedBreakpoints: Map<string, DebugProtocol.SourceBreakpoint[]>` (L79) — breakpoints keyed by absolute path for mirroring
- `adoptionInProgress: boolean` (L82) — mutex-like guard preventing concurrent adoption

**Public methods:**
- `isAdopted(pendingId)` (L98-100): Membership check on `adoptedTargets`.
- `isAdoptionInProgress()` (L105-108): Returns `adoptionInProgress` flag.
- `hasActiveChildren()` (L113-117): True if `activeChild !== null` OR `childSessions.size > 0`.
- `getActiveChild()` (L122-125): Returns `activeChild` or null.
- `shouldRouteToChild(command)` (L130-155): Returns true if command is in `dapBehavior.childRoutedCommands` (regardless of whether a child is active — callers should queue/await).
- `storeBreakpoints(sourcePath, breakpoints)` (L160-177): Normalizes path to absolute, stores in `storedBreakpoints`, immediately mirrors to `activeChild` via `setBreakpoints` if present and `mirrorBreakpointsToChild` is set.
- `createChildSession(config)` (L182-264): Full async lifecycle — guards duplicate/concurrent adoption, dynamically imports `MinimalDapClient` to avoid circular deps, connects, wires events, initializes, configures, attaches (up to 20 retries × 200ms), handles post-attach init, optionally pauses. Emits `childCreated` on success, `childError` on failure. Resets `adoptionInProgress` in both branches.
- `shutdown()` (L485-500): Calls `child.shutdown('parent shutdown')` on all entries, clears all state.

**Private methods:**
- `initializeChild(child, pendingId, _parentConfig)` (L269-285): Sends `initialize` DAP request then awaits `initialized` event (timeout from `dapBehavior.childInitTimeout` or 12000ms).
- `configureChild(child, pendingId, _parentConfig)` (L290-326): Sends `setExceptionBreakpoints`, mirrors stored breakpoints if policy requires, sends `configurationDone` unless `suppressPostAttachConfigDone`.
- `attachChild(child, pendingId, parentConfig)` (L331-354): Calls `policy.buildChildStartArgs` for command+args, retries up to 20 times with 200ms sleep, 20s per-request timeout.
- `handlePostAttachInit(child)` (L359-378): Optional 3s wait for post-attach `initialized` event; if seen and `mirrorBreakpointsToChild`, re-sends exception breakpoints and all stored breakpoints.
- `ensureChildStopped(child)` (L383-414): 15s wait for `stopped` event; if not received, fetches thread list and sends `pause` to first thread. Special js-debug quirk: if `threadId === 0`, also tries `threadId: 1`.
- `wireChildEvents(child)` (L419-437): Forwards `event` → `childEvent`, `error` → `childError(null, err)`, `close` → `childClosed` + clears all child state.
- `waitForEvent(client, eventName, timeoutMs, required)` (L442-473): Generic event/timeout race; resolves `true` on matching event, `false` on timeout; logs warning only if `required=true`.
- `sleep(ms)` (L478-480): `setTimeout` promise wrapper.

### Emitted Events
- `childCreated(pendingId, child)` — successful adoption
- `childError(pendingId | null, error)` — adoption failure or DAP client error
- `childClosed` — child connection dropped

### Notable Patterns
- **Dynamic import** of `MinimalDapClient` (L207) avoids circular dependency at module load time.
- **`adoptionInProgress` guard** (L192, L201) acts as a non-reentrant lock — only one child adoption at a time.
- **`_parentConfig` is unused** in `initializeChild` and `configureChild` (L270, L291) — marked with `void` and comments noting potential future use.
- **`stopOnEntry` and `request==='attach'` guard** (L243-247): Skips forced pause for explicit `stopOnEntry=false` or attach-mode parents (issue #124).
- **Breakpoint path normalization** (L165): Always stores/mirrors as absolute paths.