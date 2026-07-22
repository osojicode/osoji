# tests\unit\shared\adapter-policy-mock.test.ts
@source-hash: 0fddf311fd528030
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:40Z

## Unit Tests for `MockAdapterPolicy`

Tests the `MockAdapterPolicy` class from `packages/shared/src/interfaces/adapter-policy-mock.js`. Covers adapter matching, state management, variable extraction, spawn config, and child session error behavior.

### Test Suite: `MockAdapterPolicy` (L4–101)

**Test 1 — `matchesAdapter` (L5–26):**
- Returns `true` when `command` contains `'mock-adapter'` (L7–11)
- Returns `true` when any `args` element contains `'mock-adapter'` (L13–18)
- Returns `false` when neither `command` nor `args` match (L20–25)

**Test 2 — State tracking (L28–40):**
- `createInitialState()` returns `{ initialized: false, configurationDone: false }` (L29–31)
- `updateStateOnEvent?.('initialized', {}, state)` sets `state.initialized = true` (L33–34)
- After init event: `isInitialized(state)` and `isConnected(state)` both return `true` (L35–36)
- `updateStateOnCommand?.('configurationDone', {}, state)` sets `state.configurationDone = true` (L38–39)

**Test 3 — `extractLocalVariables` (L42–65):**
- Accepts `frames` (array of `{id}` objects), a scopes map keyed by frame id, and a variables map keyed by `variablesReference`
- Uses first scope of top frame (`frames[0]` → scope with `variablesReference: 11` → variables array)
- Returns array of variable objects; result contains `{ name: 'foo' }` and `{ name: 'answer' }` (L61–64)

**Test 4 — `getAdapterSpawnConfig` (L67–94):**
- When `adapterCommand: { command, args }` is provided, returns passthrough object merging command/args with `host`/`port` from config (L68–85)
- When `adapterCommand` is absent, returns `undefined` (L87–93)
- Input shape: `{ executablePath, adapterHost, adapterPort, logDir, scriptPath, adapterCommand? }`

**Test 5 — `buildChildStartArgs` throws (L96–100):**
- Calling `MockAdapterPolicy.buildChildStartArgs('pending-1', {})` throws error matching `/does not support child sessions/`

### Key Observations
- `updateStateOnEvent` and `updateStateOnCommand` are accessed with optional chaining (`?.`), indicating they may be optional on the interface
- `extractLocalVariables` and `getAdapterSpawnConfig` are also accessed with `?.`
- `MockAdapterPolicy` is a singleton/static-like object (not instantiated with `new`)
- State object is mutated in-place by `updateStateOnEvent`/`updateStateOnCommand`