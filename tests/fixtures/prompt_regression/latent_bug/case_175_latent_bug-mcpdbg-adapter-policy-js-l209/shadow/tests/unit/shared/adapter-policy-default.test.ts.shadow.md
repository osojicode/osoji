# tests\unit\shared\adapter-policy-default.test.ts
@source-hash: 9d0687523d58f921
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:43Z

## Unit Tests: `DefaultAdapterPolicy`

Tests for the `DefaultAdapterPolicy` singleton exported from `packages/shared/src/interfaces/adapter-policy.js`. Validates that the default policy provides safe no-op/fallback behaviors for all interface methods and that its state management functions work correctly.

### Test Suite: `DefaultAdapterPolicy` (L4–33)

#### Test 1: `exposes safe no-op behaviors` (L5–19)
Asserts the following properties/methods return safe, inert defaults:

| Member | Expected |
|---|---|
| `name` | `'default'` |
| `supportsReverseStartDebugging` | `false` |
| `childSessionStrategy` | `'none'` |
| `shouldDeferParentConfigDone({})` | `false` |
| `buildChildStartArgs('pending', {})` | **throws** |
| `isChildReadyEvent({ event: 'initialized' })` | `false` |
| `getDapAdapterConfiguration().type` | `'default'` |
| `resolveExecutablePath('/bin/node')` | `'/bin/node'` (passthrough) |
| `getDebuggerConfiguration()` | `{}` |
| `requiresCommandQueueing()` | `false` |
| `matchesAdapter({ command: '', args: [] })` | `false` |
| `getInitializationBehavior()` | `{}` |
| `getDapClientBehavior()` | `{}` |

Key behavioral contracts:
- `buildChildStartArgs` is explicitly expected to **throw** when called on the default policy (L10), making it an intentional unsupported-operation guard.
- `resolveExecutablePath` acts as a passthrough identity function (L13).
- `getDapAdapterConfiguration()` returns an object with `type: 'default'` (L12).

#### Test 2: `tracks state transitions via createInitialState` (L21–33)
Validates the state management lifecycle:
- `createInitialState()` returns `{ initialized: false, configurationDone: false }` (L22–24).
- `isInitialized(state)` and `isConnected(state)` both return `false` on initial state (L25–26).
- `updateStateOnCommand?.('configurationDone', {}, state)` is a no-op — `state.configurationDone` remains `false` after call (L28–29).
- `updateStateOnEvent?.('initialized', {}, state)` is a no-op — `state.initialized` remains `false` after call (L31–32).
- Both `updateStateOnCommand` and `updateStateOnEvent` are called with optional chaining (`?.`), indicating they may be undefined on the policy interface.

### Key Architectural Insights
- `DefaultAdapterPolicy` is a singleton object (not a class), used as the fallback/base implementation of the adapter policy interface.
- The policy interface includes optional methods (`updateStateOnCommand`, `updateStateOnEvent`) — callers must use optional chaining.
- `childSessionStrategy: 'none'` and `supportsReverseStartDebugging: false` signal this is the minimal/no-child-session baseline.
- The explicit `.toThrow()` on `buildChildStartArgs` (L10) documents a deliberate design decision: the default policy cannot construct child session arguments and must be overridden by a concrete policy.