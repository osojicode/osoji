# src\proxy\index.ts
@source-hash: ef92c93ee016049a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## Barrel/Index Module for `proxy` Package

This is the public API entry point for the `proxy` package. It re-exports all types and classes intended for external consumers, aggregating them from two internal modules: `proxy-manager.js` and `proxy-config.js`.

### Re-exports

- **`IProxyManager`** (L1–4, type): Interface defining the proxy manager contract, sourced from `./proxy-manager.js`.
- **`ProxyManagerEvents`** (L1–4, type): Type describing events emitted by the proxy manager, sourced from `./proxy-manager.js`.
- **`ProxyConfig`** (L6, type): Type/interface for proxy configuration shape, sourced from `./proxy-config.js`.
- **`ProxyManager`** (L8, class/value): Concrete implementation of the proxy manager, sourced from `./proxy-manager.js`.

### Architectural Notes

- Type-only exports (`IProxyManager`, `ProxyManagerEvents`, `ProxyConfig`) use `export type`, ensuring they are erased at runtime (no value-level side effects from importing these).
- `ProxyManager` is exported as a value (class), making it the sole runtime export from this barrel.
- Consumers should import from this index rather than directly from sub-modules to maintain a stable API surface.