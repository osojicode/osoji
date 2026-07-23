# src\container\dependencies.ts
@source-hash: 674e4c045256c2ee
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:14Z

## Purpose
Central dependency container factory for production use. Wires together all core implementations, process launchers, factories, and the adapter registry into a single `Dependencies` object consumed by the application root.

## Key Exports

### `Dependencies` interface (L41–58)
Structural type describing the full set of application dependencies:
- **Core implementations**: `fileSystem`, `processManager`, `networkManager`, `logger`, `environment`
- **Process launcher**: `proxyProcessLauncher`
- **Factories**: `proxyManagerFactory`, `sessionStoreFactory`
- **Adapter support**: `adapterRegistry`

### `createProductionDependencies(config?)` (L65–162)
Factory function that instantiates and wires all production dependencies. Accepts an optional `ContainerConfig` (from `./types.js`). Steps:
1. **Logger** (L67–71): Created via `createLogger('debug-mcp', ...)` with optional level/file/extra options from config.
2. **Base implementations** (L74–77): `ProcessEnvironment`, `FileSystemImpl`, `ProcessManagerImpl`, `NetworkManagerImpl`.
3. **Process launcher** (L80): `ProxyProcessLauncherImpl(processManager)`.
4. **Factories** (L83–89): `ProxyManagerFactory(proxyProcessLauncher, fileSystem, logger)` and `SessionStoreFactory()`.
5. **Adapter registry** (L94–99): `AdapterRegistry` created with `validateOnRegister: false`, `allowOverride: false`, `enableDynamicLoading: true`. Note: `enableDynamicLoading` is a non-standard extension of `AdapterRegistryConfig` (typed via intersection).
6. **Bundled adapter registration** (L101–115): Reads `globalThis.__DEBUG_MCP_BUNDLED_ADAPTERS__` (type `BundledAdapterEntry[]`) and registers each via `adapterRegistry.register(language, new factoryCtor())`. Handles async registration promises and swallows errors with `logger.warn`.
7. **Container-mode dynamic registration** (L119–149): When `process.env.MCP_CONTAINER === 'true'`, performs fire-and-forget dynamic `import()` for 7 known language adapters (`mock`, `python`, `javascript`, `ruby`, `rust`, `go`, `java`) from sibling `node_modules/@debugmcp/adapter-<lang>/dist/index.js`. Skips any language marked disabled via `isLanguageDisabled`. Failures are silently swallowed.

## Internal Types

### `BundledAdapterEntry` (L32–35)
Internal type for entries in the global bundled adapter list: `{ language: string; factoryCtor: new () => IAdapterFactory }`.

## Key Constants
- `BUNDLED_ADAPTERS_KEY = '__DEBUG_MCP_BUNDLED_ADAPTERS__'` (L36): Global key used to discover pre-bundled adapter factories injected into `globalThis`.

## Architectural Decisions
- **Fire-and-forget dynamic imports**: Container-mode adapter registration does not block dependency creation — failures are silently ignored (L137–139). This is intentional for optional adapters.
- **Bundled adapters via globalThis**: Allows external bundler/embed tools to inject adapter factories without import-time coupling.
- **`validateOnRegister: false`**: Adapter validation deferred to actual instance creation time, not registration time.
- **`enableDynamicLoading: true`**: Allows the registry to discover adapters on-demand beyond the pre-registered set.

## Dependencies (Imports)
- `ContainerConfig` from `./types.js`
- `createLogger` from `../utils/logger.js`
- Interfaces (`IFileSystem`, `IProcessManager`, `INetworkManager`, `ILogger`, `IEnvironment`, `IAdapterFactory`, `IProxyProcessLauncher`) from `@debugmcp/shared`
- Implementations (`FileSystemImpl`, `ProcessManagerImpl`, `NetworkManagerImpl`, `ProxyProcessLauncherImpl`) from `../implementations/index.js`
- `ProcessEnvironment` from `../implementations/environment-impl.js`
- `SessionStoreFactory`, `ISessionStoreFactory` from `../factories/session-store-factory.js`
- `ProxyManagerFactory`, `IProxyManagerFactory` from `../factories/proxy-manager-factory.js`
- `IAdapterRegistry`, `AdapterRegistryConfig` from `@debugmcp/shared`
- `AdapterRegistry` from `../adapters/adapter-registry.js`
- `isLanguageDisabled` from `../utils/language-config.js`