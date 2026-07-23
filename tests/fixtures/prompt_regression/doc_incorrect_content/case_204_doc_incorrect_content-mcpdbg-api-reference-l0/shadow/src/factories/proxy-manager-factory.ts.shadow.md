# src\factories\proxy-manager-factory.ts
@source-hash: 575fff5be18a778d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:24Z

## proxy-manager-factory.ts

Factory module providing production and mock implementations for creating `ProxyManager` instances, enabling dependency injection and test isolation.

### Interfaces

**`IProxyManagerFactory` (L13-15)**
Minimal factory interface with a single `create(adapter?: IDebugAdapter): IProxyManager` method. The `adapter` parameter is optional.

### Classes

**`ProxyManagerFactory` (L20-35)** — Production implementation
- Constructor (L21-25) accepts three injected dependencies: `proxyProcessLauncher: IProxyProcessLauncher`, `fileSystem: IFileSystem`, `logger: ILogger`
- `create(adapter?)` (L27-34): Instantiates a `ProxyManager` directly, passing `adapter || null` (converts `undefined` to `null` for the `ProxyManager` constructor), plus the three stored dependencies.

**`MockProxyManagerFactory` (L41-57)** — Test double
- Public mutable state for test assertions:
  - `createdManagers: IProxyManager[]` (L42) — accumulates all managers returned by `createFn`
  - `createFn?: (adapter?) => IProxyManager` (L43) — must be set before calling `create()`; throws `Error` if unset (L55)
  - `lastAdapter?: IDebugAdapter` (L44) — records the most recent adapter argument for assertion
- `create(adapter?)` (L46-56): Stores `adapter` to `lastAdapter`, delegates to `createFn` if set, pushes result to `createdManagers`; throws if `createFn` is not configured

### Key Patterns
- `adapter || null` at L29 coerces `undefined` → `null` before passing to `ProxyManager`, suggesting `ProxyManager`'s first parameter accepts `IDebugAdapter | null` but not `undefined`.
- `MockProxyManagerFactory` is co-located with the production factory (not in a test file), making it available as a shared test utility across the project.
- `createdManagers` only tracks managers produced through `createFn` (the `throw` path never pushes), so its count exactly equals successful `create()` calls.