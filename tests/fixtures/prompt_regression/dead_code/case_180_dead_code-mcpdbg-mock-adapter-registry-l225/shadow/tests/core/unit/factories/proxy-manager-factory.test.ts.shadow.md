# tests\core\unit\factories\proxy-manager-factory.test.ts
@source-hash: d0532259cb00db76
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:33Z

## Purpose
Unit tests for `ProxyManagerFactory` and `MockProxyManagerFactory` from `src/factories/proxy-manager-factory.ts`. Verifies factory creation behavior, dependency injection, instance independence, adapter passthrough, and mock factory tracking semantics.

## Test Structure

### Top-level describe: `ProxyManagerFactory` (L11–437)
Shared fixtures set up in `beforeEach` (L96–102):
- `mockProxyProcessLauncher`: `{ launchProxy: vi.fn() }` (L97–99)
- `mockFileSystem`: from `createMockFileSystem()` (L100)
- `mockLogger`: from `createMockLogger()` (L101)

### Helper: `createMockDebugAdapter()` (L17–94)
Returns a fully stubbed `IDebugAdapter` using `DebugLanguage.MOCK`. Stubs all lifecycle, state, environment, executable, configuration, path translation, DAP protocol, connection, error handling, feature support, and EventEmitter methods. Used to test adapter-aware factory create calls.

---

### Inner describe: `ProxyManagerFactory` (L108–268)
Tests the real `ProxyManagerFactory` class:

| Test | Lines | Assertion |
|------|-------|-----------|
| Creates ProxyManager with correct dependencies | L109–127 | `factory.create()` returns `ProxyManager` instance with expected interface methods |
| Creates independent instances on multiple calls | L129–145 | Two `create()` calls yield distinct `ProxyManager` instances |
| Does not retain references to created instances | L147–166 | 3 instances from loop are all distinct (factory is stateless) |
| Passes same dependencies to all created instances | L168–186 | Private fields `proxyProcessLauncher`, `fileSystem`, `logger` match original mocks via `(factory as any)` |
| Creates ProxyManager with provided adapter | L188–207 | `factory.create(mockAdapter)` returns `ProxyManager` with correct interface |
| Creates ProxyManager with null when no adapter provided | L209–221 | `factory.create()` (no adapter) still returns valid `ProxyManager` |
| Creates different instances for different adapters | L223–241 | Two calls with different adapters yield distinct `ProxyManager` instances |
| Does not mutate dependencies between create calls | L243–267 | After multiple `create()` calls with/without adapters, factory private fields unchanged |

---

### Inner describe: `MockProxyManagerFactory` (L270–437)
Tests the `MockProxyManagerFactory` test-double class:

| Test | Lines | Key Behavior |
|------|-------|--------------|
| Throws when `createFn` not set | L271–275 | Error: `'MockProxyManagerFactory requires createFn to be set in tests'` |
| Uses provided `createFn` | L277–287 | `createFn` is called once; returned value is the result |
| Tracks created managers | L289–307 | `createdManagers` array grows with each `create()` call |
| Allows `createFn` to be called multiple times | L309–322 | 3 calls → `createFn` called 3×, `createdManagers.length === 3` |
| Maintains independent state between factory instances | L324–342 | Two `MockProxyManagerFactory` instances have separate `createdManagers` arrays |
| Tracks `lastAdapter` | L344–361 | `lastAdapter` is `undefined` initially and after no-adapter calls; set to adapter after adapter calls |
| Passes adapter to `createFn` | L363–379 | `createFn` receives `undefined` when called without adapter, receives adapter object when provided |
| Tracks adapter even when `createFn` throws | L381–391 | `lastAdapter` is updated before `createFn` throws (or throw comes from missing `createFn`) |
| Updates `lastAdapter` on each call | L393–412 | `lastAdapter` reflects the most recent call's adapter argument (including reset to `undefined`) |
| Handles `createFn` that uses adapter parameter | L414–436 | `createFn` can branch on adapter presence; `createdManagers` tracks all results correctly |

## Key Invariants Being Tested
- `ProxyManagerFactory.create()` is a pure factory (stateless, no instance tracking)
- `ProxyManagerFactory` stores constructor dependencies as private fields accessible via `(factory as any)`
- `MockProxyManagerFactory.create()` MUST throw if `createFn` is not set
- `MockProxyManagerFactory.lastAdapter` is always updated before `createFn` invocation (evidenced by L381–391 where throw still results in `lastAdapter` being set)
- `MockProxyManagerFactory.createdManagers` is an append-only tracking array

## Dependencies
- **Production under test**: `ProxyManagerFactory`, `MockProxyManagerFactory` from `src/factories/proxy-manager-factory.js`
- **Production types**: `ProxyManager`, `IProxyManager` from `src/proxy/proxy-manager.js`; `IProxyProcessLauncher` from `src/interfaces/process-interfaces.js`; `IFileSystem`, `ILogger` from `src/interfaces/external-dependencies.js`; `IDebugAdapter`, `DebugLanguage` from `@debugmcp/shared`
- **Test utilities**: `createMockLogger`, `createMockFileSystem` from `tests/test-utils/helpers/test-dependencies.js`; `MockProxyManager` from `tests/test-utils/mocks/mock-proxy-manager.js`
