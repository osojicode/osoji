# tests\test-utils\mocks\mock-proxy-manager.ts
@source-hash: 64d3b2b16e4014c5
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:47Z

## MockProxyManager (L11–253)

A test double for `IProxyManager` that extends Node.js `EventEmitter`. Used in unit tests to simulate the full lifecycle of a debug proxy session without spawning real processes.

### Class Overview
`MockProxyManager` (L11) implements `IProxyManager` and mirrors all its methods. It tracks every call for assertion in tests and provides controllable failure/delay injection.

---

### State Fields (private, L12–18)
| Field | Type | Purpose |
|---|---|---|
| `_isRunning` | `boolean` | Tracks proxy running state |
| `_currentThreadId` | `number \| null` | Active thread after stop event |
| `_config` | `ProxyConfig \| null` | Config passed to `start()` |
| `_dapRequestHandler` | `Function \| null` | Override for custom DAP responses |
| `_dryRunCompleted` | `boolean` | Set when dry-run mode finishes |
| `_dryRunCommand` | `string?` | Captured dry-run command |
| `_dryRunScript` | `string?` | Captured dry-run script path |

---

### Public Call-Tracking Fields (L21–23)
- `startCalls: ProxyConfig[]` — accumulates all configs passed to `start()`
- `stopCalls: number` — count of `stop()` invocations
- `dapRequestCalls: Array<{command, args?, options?}>` — all DAP requests sent

### Public Behavior-Control Fields (L26–29)
- `shouldFailStart: boolean` — causes `start()` to throw
- `startDelay: number` — adds artificial async delay to `start()`
- `shouldFailDapRequests: boolean` — causes `sendDapRequest()` to throw
- `dapRequestDelay: number` — adds artificial async delay to `sendDapRequest()`

---

### Key Methods

**`start(config)` (L35–70)**
Pushes config to `startCalls`, optionally fails or delays, then sets internal state. Uses `process.nextTick` to asynchronously emit:
- If `config.dryRunSpawn`: emits `'dry-run-complete'` with `'python'` and `config.scriptPath` (hardcoded command `'python'` at L56)
- Otherwise: emits `'adapter-configured'`, `'initialized'`, and optionally `'stopped'` if `config.stopOnEntry` is true (threadId=1)

**`stop()` (L72–84)**
Increments `stopCalls`, clears all state, emits `'exit'` with code `0` via `process.nextTick`.

**`sendDapRequest<T>(command, args?, options?)` (L86–181)**
Records call, checks `_isRunning` (throws if false), checks `shouldFailDapRequests`, applies delay, then:
1. Delegates to `_dapRequestHandler` if set
2. Otherwise returns hardcoded mock responses for: `setBreakpoints`, `stackTrace`, `scopes`, `variables`, `next`/`stepIn`/`stepOut` (emit `'stopped'` via nextTick), `continue` (emits `'continued'`), and default (`{success: true}`)

**`isRunning()` (L183–185)** / **`getCurrentThreadId()` (L187–189)**
Simple state accessors implementing `IProxyManager`.

---

### Test Helper Methods

| Method | Lines | Purpose |
|---|---|---|
| `setDapRequestHandler(handler)` | L192–194 | Override DAP responses with custom async function |
| `simulateEvent<K>(event, ...args)` | L196–206 | Emit any `ProxyManagerEvents` event; also updates dry-run state when event is `'dry-run-complete'` |
| `simulateStopped(threadId, reason)` | L208–211 | Set `_currentThreadId` and emit `'stopped'` |
| `simulateError(error)` | L213–215 | Emit `'error'` event |
| `simulateExit(code, signal?)` | L217–221 | Set not-running, emit `'exit'` |
| `hasDryRunCompleted()` | L223–225 | Returns `_dryRunCompleted` |
| `getDryRunSnapshot()` | L227–235 | Returns `{command, script}` if dry-run done, else `undefined` |
| `reset()` | L237–253 | Resets ALL state, call counters, behavior flags, listeners — intended for `beforeEach` teardown |

---

### Event Emissions Summary
| Event | Emitted by | Condition |
|---|---|---|
| `'dry-run-complete'` | `start()`, `simulateEvent()` | `config.dryRunSpawn === true` |
| `'adapter-configured'` | `start()` | normal (non-dry-run) start |
| `'initialized'` | `start()` | normal start |
| `'stopped'` | `start()`, `sendDapRequest()`, `simulateStopped()` | stopOnEntry or step commands |
| `'continued'` | `sendDapRequest('continue')` | |
| `'exit'` | `stop()`, `simulateExit()` | |
| `'error'` | `simulateError()` | |

---

### Usage Pattern
Tests should call `reset()` in `beforeEach` to clear all state and listeners between tests. Use `setDapRequestHandler()` for scenario-specific DAP responses. Use `simulate*()` helpers to trigger lifecycle events independent of `start()`/`stop()` flow.
