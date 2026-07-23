# tests\unit\test-utils\mock-validation.test.ts
@source-hash: 314c234e5992125c
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:45Z

## Purpose
Unit tests for the auto-mock generation and validation utilities in `./auto-mock.js`. Verifies `createMockFromInterface`, `validateMockInterface`, `createValidatedMock`, and `createEventEmitterMock` behave correctly across a range of scenarios.

## Test Fixture Classes

### `TestClass` (L15–50)
Local class used as the primary mock target. Has:
- Public properties: `property` (L16), `getter`/`setter` (L27–33)
- Public methods: `method(arg1, arg2)` (L19), `asyncMethod()` (L23), `isActive()` (L39), `hasFeature()` (L43), `getConfig()` (L47)
- Private: `_privateProperty` (L17), `_privateMethod()` (L35)

### `ExtendedClass` (L52–56)
Extends `TestClass`, adds `extendedMethod()`. Used to test inherited-method behaviour.

### `TestEventEmitter` (L58–66)
Extends Node.js `EventEmitter`, adds `customMethod()` and `start()`. Used to test EventEmitter mock merging and validation.

---

## Test Suite Structure

### `createMockFromInterface` (L69–139)
| Test | What it covers |
|---|---|
| L70–77 | All public methods become `vi.fn()` mocks |
| L79–84 | Boolean-returning methods default to `false` |
| L86–90 | Object-returning methods default to `undefined` |
| L92–99 | `excludeMethods: /regex/` removes matching methods |
| L101–108 | `excludeMethods: string[]` removes named methods |
| L110–120 | `defaultReturns` map overrides return values |
| L122–129 | Inherited methods included by default |
| L131–138 | `includeInherited: false` restricts to own methods only |

### `validateMockInterface` (L141–239)
| Test | What it covers |
|---|---|
| L142–158 | Full mock passes without throwing |
| L160–171 | Missing public method throws `/Missing member 'method'/` |
| L173–195 | Missing private method warns (`console.warn`) but does not throw; expects message containing `"Private member '_privateMethod'"` |
| L197–213 | Wrong-type member (string instead of function) throws `/Member 'method' should be a function/` |
| L215–238 | Extra mock members warn with `"Mock has extra member 'extraMethod'"` |

### `createValidatedMock` (L241–260)
| Test | What it covers |
|---|---|
| L242–249 | Combined create+validate in one call; result has correct vi.fn() mocks |
| L251–259 | `defaultReturns` option propagated correctly |

### `createEventEmitterMock` (L262–298)
| Test | What it covers |
|---|---|
| L263–275 | Core EventEmitter methods (`on`, `once`, `emit`, `off`, `removeListener`, `removeAllListeners`) are present; `on` chains (returns `mock`) |
| L277–286 | Generic type param `<TestEventEmitter>` with additional methods merged in |
| L288–298 | Resulting mock passes `validateMockInterface` for `TestEventEmitter` |

### Integration Test (L301–343)
Simulates a `ProxyManagerLike` class (EventEmitter subclass with DAP-style API). Verifies `createEventEmitterMock` + `validateMockInterface` round-trip works for realistic production-like classes. Confirms `isRunning()` returns `false` and `getCurrentThreadId()` returns `null` (L340–341).

---

## Key Behavioral Contracts Exercised

- **Boolean method heuristic**: Methods named `is*` or `has*` default to returning `false` (not `undefined`).
- **Private vs public distinction**: `validateMockInterface` treats underscore-prefixed members as private (warn-only) vs public (throw on missing/wrong-type).
- **Inheritance traversal**: `createMockFromInterface` walks prototype chain by default; opt-out via `includeInherited: false`.
- **EventEmitter chaining**: `mock.on(...)` must return `mock` itself (L274).
- **Extra-member handling**: `validateMockInterface` warns (does not throw) on extra mock members.

---

## Dependencies
- `vitest` (`describe`, `it`, `expect`, `vi`) — test runner and spy utilities (L5)
- `./auto-mock.js` — the SUT; exports the four mock utilities (L7–11)
- `events` (`EventEmitter`) — Node.js built-in for `TestEventEmitter` and `ProxyManagerLike` fixtures (L12)