# tests\core\unit\factories\proxy-manager-factory.test.ts
@source-hash: d0532259cb00db76
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:39Z

## Unit Tests: ProxyManagerFactory and MockProxyManagerFactory

Tests covering both the real `ProxyManagerFactory` and the test-utility `MockProxyManagerFactory` classes, verifying factory contract behavior, dependency injection, instance isolation, and adapter tracking.

### Test Structure

**Outer suite** (`ProxyManagerFactory`, L11–437): Shares `beforeEach`/`afterEach` setup across two inner suites.

**Shared fixtures** (L12–106):
- `mockProxyProcessLauncher`: minimal `{ launchProxy: vi.fn() }` (L97–99)
- `mockFileSystem`: via `createMockFileSystem()` (L100)
- `mockLogger`: via `createMockLogger()` (L101)

**`createMockDebugAdapter()` helper** (L17–94): Builds a fully stubbed `IDebugAdapter` implementing all interface members (lifecycle, state, environment validation, executable management, DAP protocol, EventEmitter, etc.) with `vi.fn()` stubs. Uses `DebugLanguage.MOCK` and `as unknown as IDebugAdapter` cast.

---

### Inner Suite: `ProxyManagerFactory` (L108–268)

| Test | Lines | What it verifies |
|------|-------|-----------------|
| Creates ProxyManager with correct deps | 109–127 | `factory.create()` returns `ProxyManager` instance with all interface methods |
| Independent instances | 129–145 | Multiple `create()` calls return distinct `ProxyManager` objects |
| No retained references | 147–166 | Three creates yield three distinct instances; factory has no instance tracking |
| Passes same dependencies | 168–186 | Internal fields `proxyProcessLauncher`, `fileSystem`, `logger` match the injected mocks (accessed via `(factory as any)`) |
| Create with adapter | 188–207 | `factory.create(mockAdapter)` returns `ProxyManager` with correct interface |
| Create without adapter (null) | 209–221 | `factory.create()` (no arg) still returns `ProxyManager` |
| Different instances for different adapters | 223–241 | Two adapters → two distinct `ProxyManager` instances |
| No dependency mutation | 243–267 | After mixed `create()` calls, internal deps remain unchanged |

---

### Inner Suite: `MockProxyManagerFactory` (L270–437)

| Test | Lines | What it verifies |
|------|-------|-----------------|
| Throws when `createFn` unset | 271–275 | Error message: `'MockProxyManagerFactory requires createFn to be set in tests'` |
| Uses provided `createFn` | 277–287 | Delegates to `createFn`, returns its result |
| Tracks created managers | 289–307 | `createdManagers` array grows on each `create()` call |
| Multiple `createFn` calls | 309–322 | Called 3× → `createdManagers.length === 3` |
| Independent state between instances | 324–342 | Two factory instances maintain separate `createdManagers` arrays |
| Tracks last adapter | 344–361 | `lastAdapter` updates on each call; `undefined` when no adapter passed |
| Passes adapter to `createFn` | 363–379 | `createFn` receives `undefined` or the adapter object |
| Tracks adapter even when `createFn` throws | 381–391 | `lastAdapter` is set before the error is thrown |
| Updates `lastAdapter` on each call | 393–412 | Last adapter reflects most-recent call; `undefined` when called without arg |
| `createFn` can dispatch on adapter | 414–436 | Factory correctly routes to different manager instances based on adapter presence |

---

### Key Dependencies
- **SUT imports**: `ProxyManagerFactory`, `MockProxyManagerFactory` from `src/factories/proxy-manager-factory.js`; `ProxyManager`, `IProxyManager` from `src/proxy/proxy-manager.js`
- **Test utilities**: `createMockLogger`, `createMockFileSystem` from `test-utils/helpers/test-dependencies.js`; `MockProxyManager` from `test-utils/mocks/mock-proxy-manager.js`
- **Shared interfaces**: `IProxyProcessLauncher`, `IFileSystem`, `ILogger`, `IDebugAdapter`, `DebugLanguage` from `@debugmcp/shared` and internal interfaces

### Architectural Notes
- Tests validate the factory pattern contract: stateless creation, shared dependency injection, no instance leakage.
- `MockProxyManagerFactory` tests verify the test-helper's own contract: `createFn` delegation, `createdManagers` tracking, `lastAdapter` tracking (including pre-throw persistence).
- Internal fields of `ProxyManagerFactory` are accessed via `(factory as any)` cast (L178–181, L259–262) to verify dependency identity without exposing them in the public API.
