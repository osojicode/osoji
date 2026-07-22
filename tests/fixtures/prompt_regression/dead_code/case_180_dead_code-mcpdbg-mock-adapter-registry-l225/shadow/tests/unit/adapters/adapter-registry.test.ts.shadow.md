# tests\unit\adapters\adapter-registry.test.ts
@source-hash: a824e7abc2bb9f9d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:33Z

## Unit Tests: AdapterRegistry

Tests for `AdapterRegistry`, `getAdapterRegistry`, and `resetAdapterRegistry` from `src/adapters/adapter-registry.ts`. Validates all major registry behaviors: factory registration, adapter creation, lifecycle management, dynamic loading, disposal, and singleton helpers.

### Test Helpers

**`createAdapterStub()` (L5-33)**
Creates a functional mock adapter with a real in-memory event emitter (Map-based). Mocks: `initialize`, `on`, `once`, `dispose` (all vi.fn()). `emit` is a real function that dispatches to registered handlers. `once` correctly removes the handler after first invocation.

**`createFactory(overrides?)` (L35-44)**
Creates a mock adapter factory with:
- `validate`: resolves `{ valid: true, errors: [], warnings: [] }`
- `getMetadata`: returns `{ name: 'mock', version: '1.0.0' }`
- `createAdapter`: returns an `createAdapterStub()` instance
- `__adapter`: reference to the internal adapter stub (for assertions)
- Accepts partial overrides via spread

### Test Coverage

| Test | Lines | Key Assertion |
|---|---|---|
| Register/unregister with validation | L52-62 | `validate` called on register; `unregister` returns true/false |
| Duplicate registration throws | L64-70 | `DuplicateRegistrationError` on second `register` with same key |
| Validation failure throws | L72-83 | `FactoryValidationError` when `validate` resolves `valid: false` |
| Max instances enforcement | L85-112 | Second `create` throws `/Maximum adapter instances/`; `getActiveAdapterCount()` tracks correctly |
| Dynamic loading success | L114-137 | `loader.loadAdapter` called on unknown language; adapter returned |
| Dynamic loading failure → `AdapterNotFoundError` | L139-156 | Loader rejection converts to `AdapterNotFoundError` |
| Auto-dispose on state change | L158-199 | `stateChanged` event `'disconnected'` starts timer; dispose called after timeout; `'debugging'` clears timer |
| `disposeAll` | L201-226 | Disposes all adapters; count goes to 0; double-dispose does not throw |
| Override registration | L228-237 | `allowOverride: true` allows re-registration; `getSupportedLanguages()` deduplicates |
| `listLanguages` — static | L240-248 | Returns only registered language names |
| `listLanguages` — dynamic merge | L250-267 | Merges installed=true from loader; excludes installed=false |
| `listLanguages` — loader fallback | L269-280 | Loader error falls back to registered languages |
| `listAvailableAdapters` — static | L284-296 | Returns `{ name, packageName: '@debugmcp/adapter-mock', description: undefined, installed: true }` |
| `listAvailableAdapters` — dynamic merge | L298-317 | Registered adapter overrides `installed` to true; loader-only adapters included |
| `listAvailableAdapters` — loader fallback | L319-332 | Loader error falls back to registered-only list |
| `getAdapterInfo` | L336-350 | Returns `{ language, available, activeInstances }`; undefined for unknown |
| `getAllAdapterInfo` | L353-362 | Returns Map with all registered languages |
| Unregister emits error on disposal failure | L366-396 | Async dispose error emitted via `registry.on('error', ...)` |
| `disposeAll` resolves on disposal failure | L398-421 | Does not reject; `getActiveAdapterCount()` returns 0 |
| Singleton `getAdapterRegistry` | L429-433 | Same instance on repeated calls |
| Singleton `resetAdapterRegistry` | L435-440 | New instance after reset |

### Setup/Teardown
- `beforeEach` (L47-50): Restores mocks via `vi.restoreAllMocks()`; stubs `MCP_CONTAINER` env var to undefined
- `afterEach` in singleton suite (L425-427): Calls `resetAdapterRegistry()` to clean global state

### Notable Patterns
- `loader` accessed via `vi.spyOn(registry as any, 'loader', 'get')` — tests treat it as a getter property (L121, L141, L255, L274, L303, L324)
- Auto-dispose test (L158-199) uses `vi.useFakeTimers()`/`vi.useRealTimers()` to control timer advancement
- `adapterConfig` shape used throughout: `{ sessionId, adapterHost, adapterPort, logDir, scriptPath, executablePath, launchConfig }`
- `factory as any` casts used throughout because the stub does not fully satisfy the `AdapterFactory` interface type
- packageName convention: `@debugmcp/adapter-{name}` (verified at L292)