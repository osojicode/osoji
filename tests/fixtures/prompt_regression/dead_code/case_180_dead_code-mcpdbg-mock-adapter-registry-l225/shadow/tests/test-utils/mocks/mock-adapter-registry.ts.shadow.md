# tests\test-utils\mocks\mock-adapter-registry.ts
@source-hash: b9d3e1d723db38b3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:02Z

## Mock Adapter Registry — Test Utility

Provides factory functions and assertion helpers for mocking the `IAdapterRegistry` interface (from `@debugmcp/shared`) in Vitest-based tests. All returned objects satisfy the `IAdapterRegistry` contract with `vi.fn()` spies.

---

### Factory Functions

#### `createMockAdapterRegistry` (L13–140)
Returns a fully-wired `IAdapterRegistry` mock with two pre-configured languages: `'python'` and `'mock'`.

**Registry-level methods:**
| Method | Behavior |
|---|---|
| `getSupportedLanguages` | Returns `['python', 'mock']` |
| `isLanguageSupported` | Real `includes()` check against `['python', 'mock']` |
| `create` | Async; returns a full mock `IDebugAdapter` (see below) |
| `register` | Resolves `undefined` |
| `unregister` | Returns `true` |
| `getAdapterInfo` | Looks up a pre-built `Map` keyed by language string |
| `getAllAdapterInfo` | Returns the entire `Map<string, AdapterInfo>` |
| `disposeAll` | Resolves `undefined` |
| `getActiveAdapterCount` | Returns `0` |

**Mock `IDebugAdapter` returned by `create` (L49–124):**  
The adapter object is constructed inline. Notable mocked methods:
- `buildAdapterCommand` (L72–76): Uses `config.executablePath || 'node'`, args = `['mock-adapter.js', '--port', String(config.adapterPort)]`. Marked "CRITICAL METHOD" in comment.
- `getState` → `'ready'`; `isReady` → `true`; `isConnected` → `true`
- `getCurrentThreadId` → `1`
- `validateEnvironment` → `{ valid: true, errors: [], warnings: [] }`
- `translateErrorMessage` → `err.message` (identity via `.message` access)
- Full `EventEmitter` surface: `on`, `off`, `emit`, `once`, `removeListener`, `removeAllListeners`, `setMaxListeners`, `getMaxListeners` (→ `10`), `listeners`/`rawListeners` (→ `[]`), `listenerCount` (→ `0`), `prependListener`, `prependOnceListener`, `eventNames` (→ `[]`), `addListener`

**Pre-built `AdapterInfo` entries (L17–40):**
- `'python'`: `DebugLanguage.PYTHON`, extensions `['.py']`, `available: true`, `activeInstances: 0`
- `'mock'`: `DebugLanguage.MOCK`, extensions `['.mock', '.js']`, `available: true`, `activeInstances: 0`

---

#### `createMockAdapterRegistryWithErrors` (L146–157)
Extends `createMockAdapterRegistry()` and overrides methods to simulate failure states:
- `getSupportedLanguages` → `[]`
- `isLanguageSupported` → `false`
- `create` → rejects with `Error('Adapter not found')`
- `getAdapterInfo` → `undefined`
- `getAllAdapterInfo` → empty `Map`

---

#### `createMockAdapterRegistryWithLanguages(languages: string[])` (L163–192)
Extends `createMockAdapterRegistry()` and overrides to support an arbitrary language list:
- `getSupportedLanguages` → `languages`
- `isLanguageSupported` → real `includes()` check
- `getAdapterInfo` / `getAllAdapterInfo` → fresh `Map` built from `languages`, with `AdapterInfo` entries that do **not** include `fileExtensions` (unlike the base factory)

---

### Assertion Helpers

#### `expectAdapterRegistryLanguageCheck(mock, language, expectedCalls?)` (L197–204)
Asserts `mock.isLanguageSupported` was called with `language` exactly `expectedCalls` times (default `1`). Uses bare `expect` — relies on Vitest globals being in scope.

#### `expectAdapterCreation(mock, language)` (L209–220)
Asserts `mock.create` was called with `language` and an object containing `{ sessionId: String, executablePath: String }`.

#### `resetAdapterRegistryMock(mock)` (L225–232)
Iterates `Object.values(mock)` and calls `.mockReset()` on any value that is a function with `'mockReset'` in it. **Does not restore original implementations** — only resets call history and return values.

---

### Architectural Notes
- All mock objects are plain object literals; no class inheritance.
- `resetAdapterRegistryMock` only resets top-level registry methods, not the nested adapter methods returned by `create`.
- `createMockAdapterRegistryWithErrors` uses direct property assignment on the object returned by `createMockAdapterRegistry`, which works because all methods are plain enumerable own properties.
- `translateErrorMessage` accesses `err.message` (L101) — the `err` parameter is typed as `unknown` implicitly; if callers pass a non-`Error` value this will return `undefined`.