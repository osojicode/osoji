# packages\shared\tests\unit\adapter-policy-js.spec.ts
@source-hash: 494eb56e2db92070
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:38Z

## Unit Tests for `JsDebugAdapterPolicy`

Tests the `JsDebugAdapterPolicy` class from `../../src/interfaces/adapter-policy-js.js`, covering all major policy behaviors for the js-debug adapter integration.

### Test Helper (L5-L13)
- `createStackFrame(id, file)`: Factory producing a `DebugProtocol.StackFrame & { file?: string }` fixture with `id`, `name: "frame-{id}"`, `line: 1`, `column: 1`, and `file`.

### Test Suites

**`buildChildStartArgs` (L16-L26)**
- Verifies that calling `JsDebugAdapterPolicy.buildChildStartArgs('pending-1', { type: 'pwa-node' })` produces `command: 'attach'` and args containing `request: 'attach'`, `__pendingTargetId: 'pending-1'`, `continueOnAttach: true`.

**`filterStackFrames` (L28-L43)**
- Verifies `<node_internals>/...` frames are filtered out, keeping user-space frames.
- Fallback behavior: if all frames are internal, returns the full (unfiltered) list (length 1 kept).

**`extractLocalVariables` (L45-L94)**
- Returns `[]` on empty frame list (L48-L51).
- Filters out special JS variables (`this`, `__proto__`) by default; only includes `'value'` (L53-L73).
- When 4th argument is `true`, includes special variables like `this` (L75-L93).
- Scope matching: `'Locals'` (L57) and `'Local'` (L79) scope names are both recognized by the implementation.

**`command queueing` (L96-L135)**
- `shouldQueueCommand('initialize', state)` → `shouldQueue: false` (L97-L101).
- `shouldQueueCommand('threads', state)` (before init response) → `shouldQueue: true`, `shouldDefer: false` (L103-L108).
- After `state.initializeResponded = true` and `state.configurationDone = false`, `shouldQueueCommand('launch', state)` → `shouldQueue: true`, `shouldDefer: true` (L110-L118).
- `processQueuedCommands` reorders: configuration commands (`setBreakpoints`) → `configurationDone` → start commands (`launch`) → others (`threads`) (L120-L134).

**`state helpers` (L137-L150)**
- `updateStateOnCommand('launch', ...)` sets `state.startSent = true`.
- `updateStateOnEvent('initialized', ...)` sets `state.initialized = true`.
- After `state.initializeResponded = true`: `isConnected(state)` and `isInitialized(state)` both return `true`.

**`matchesAdapter` (L152-L168)**
- Returns `true` when args contain `js-debug` token (e.g., `vsDebugServer.cjs`).
- Returns `false` for non-js-debug commands (e.g., Python).

**`getInitializationBehavior` (L170-L176)**
- Asserts `deferConfigDone: true` and `addRuntimeExecutable: true`.

**`DAP client behavior` (L178-L206)**
- `normalizeAdapterId('javascript')` → `'pwa-node'`.
- `handleReverseRequest` for `startDebugging` command: sends one response, returns `{ handled: true, createChildSession: true, childConfig: { pendingId: 'child-1' } }`.
- Uses a mock `context` with `adoptedTargets: Set<string>` and `sendResponse` callback.

**`getAdapterSpawnConfig` (L208-L229)**
- With `adapterCommand`, `adapterHost`, `adapterPort`, `logDir` inputs, returns spawn config matching `{ command, args, host, port, logDir }`.

### Key Architectural Notes
- All tested methods are accessed as static members of `JsDebugAdapterPolicy` (not instantiated).
- Optional-chained access (`!`) used on `filterStackFrames`, `extractLocalVariables`, `shouldQueueCommand`, etc., indicates these methods are optional on the policy interface — tests assert they are defined.
- State mutation is tested by casting `createInitialState()` result to `any` and directly writing fields (`state.initializeResponded`, `state.configurationDone`), revealing the shape of the internal state object.
- The `processQueuedCommands` sort order contract: **config commands < configurationDone < start commands < other commands**.
