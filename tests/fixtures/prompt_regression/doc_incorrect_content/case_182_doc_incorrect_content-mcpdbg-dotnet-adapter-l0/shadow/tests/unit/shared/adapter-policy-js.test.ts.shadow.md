# tests\unit\shared\adapter-policy-js.test.ts
@source-hash: 51adcd2b64694809
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:22Z

## Purpose
Unit test suite for `JsDebugAdapterPolicy` — the JavaScript/Node.js debug adapter policy class. Verifies DAP lifecycle management, command queueing, state tracking, stack frame filtering, variable extraction, and handshake flows.

## Test Structure
Single top-level `describe('JsDebugAdapterPolicy')` (L5) with 9 `it` blocks and one nested `describe('performHandshake')` (L144) containing 2 async tests.

## Key Tests

### `buildChildStartArgs` (L6–16)
Verifies that attaching to a child process uses `command: 'attach'` with args containing `__pendingTargetId`, `type: 'pwa-node'`, and `continueOnAttach: true`.

### `isChildReadyEvent` (L18–22)
Checks that `'thread'` and `'stopped'` events are considered ready; `'continued'` is not.

### `filterStackFrames` (L24–37)
Validates that frames with `<node_internals>` are excluded when `includeInternal=false` (returns 2 of 3 frames), and all 3 are returned when `true`.

### `extractLocalVariables` (L39–71)
Uses fixture with frames/scopes/variables. Confirms that `'this'`, `'__proto__'`, and `'$internal'` prefixed names are excluded by default; passing `true` as 4th arg includes `'this'`.

### `shouldQueueCommand` (L73–87)
State machine progression: queues `'launch'` before `initializeResponded`; queues `'setBreakpoints'` after `initializeResponded` but before full init/configDone; does not queue `'threads'` after full initialization.

### `processQueuedCommands` (L89–104)
Verifies JS-specific ordering: `setBreakpoints → configurationDone → launch → evaluate` from an out-of-order input.

### State tracking (L106–115)
`createInitialState()` starts disconnected/uninitialized; after setting `initializeResponded=true` and calling `updateStateOnEvent('initialized', {}, state)`, both `isConnected` and `isInitialized` return `true`.

### `updateStateOnResponse` (L117–123)
Calling with `'initialize'` sets `state.initializeResponded = true`.

### `matchesAdapter` (L125–132)
Returns `true` for `{ command: 'node', args: ['--inspect', 'js-debug'] }`; `false` for Python debugpy args.

### `getInitializationBehavior` / `requiresCommandQueueing` / `resolveExecutablePath` (L134–142)
- `deferConfigDone: true`, `addRuntimeExecutable: true`
- `requiresCommandQueueing()` returns `true`
- `resolveExecutablePath()` defaults to `'node'`; accepts override path

### `performHandshake` — launch flow (L145–185)
Sets up fake EventEmitter-based `proxyManager` with `isRunning: () => true`. Emits `'dap-event'` with `{ event: 'initialized' }` to unblock handshake. Expects `sendDapRequest` called with: `initialize`, `setExceptionBreakpoints({filters:[]})`, `setBreakpoints` (with correct source/line), `configurationDone`, and `launch`.

### `performHandshake` — attach flow (L187–219)
`dapLaunchArgs` includes `request: 'attach'`, `attachSimplePort: 9229`, `type: 'pwa-node'`. Emits `'dap-event'` with string `'initialized'` (not object). Expects `attach` DAP call with `port: 9229`; no `launch` call.

## Test Infrastructure
- **Vitest** (`describe`, `it`, `expect`, `vi`) for assertions and mocking (L1)
- **Node.js `EventEmitter`** used as base for mock `proxyManager` in handshake tests (L2, L147, L189)
- `vi.useFakeTimers()` / `vi.advanceTimersByTimeAsync(0)` used to control async timer resolution in handshake tests (L146, L170, L188, L210)
- `vi.fn().mockResolvedValue({})` for `sendDapRequest` mock (L148, L190)
- All casts via `as any` to bypass TypeScript type checks on fixtures

## Notable Patterns
- Two `performHandshake` tests emit `'initialized'` differently: launch test emits `{ event: 'initialized' }` (object, L169); attach test emits the string `'initialized'` (L209) — the policy must handle both forms or only one is tested accurately.
- State mutation directly on `as any` cast (L79, L83, L84, L111) simulates state progression.
- Optional chaining on `updateStateOnResponse?.` (L121) suggests the method may be optional on the policy interface.
