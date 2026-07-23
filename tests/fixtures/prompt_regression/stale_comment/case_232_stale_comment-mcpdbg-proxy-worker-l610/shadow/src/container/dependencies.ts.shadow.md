# src\container\dependencies.ts
@source-hash: 674e4c045256c2ee
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:24Z

## Purpose
Central dependency wiring module for production use. Instantiates all core implementations, process launchers, factories, and the adapter registry, returning them as a unified `Dependencies` object. Also handles bundled and container-mode dynamic adapter registration.

## Key Exports

### `Dependencies` interface (L41–58)
Complete dependency container shape:
- `fileSystem: IFileSystem` — file I/O abstraction
- `processManager: IProcessManager` — OS process abstraction
- `networkManager: INetworkManager` — network abstraction
- `logger: ILogger` — structured logger
- `environment: IEnvironment` — env var access
- `proxyProcessLauncher: IProxyProcessLauncher` — launches proxy processes
- `proxyManagerFactory: IProxyManagerFactory` — creates proxy managers
- `sessionStoreFactory: ISessionStoreFactory` — creates session stores
- `adapterRegistry: IAdapterRegistry` — adapter discovery and registration

### `createProductionDependencies(config?)` (L65–162)
Factory function; accepts optional `ContainerConfig` (defaults to `{}`). Instantiation order:
1. **Logger** (L67–71): `createLogger('debug-mcp', { level, file, ...loggerOptions })`
2. **Base impls** (L74–77): `ProcessEnvironment`, `FileSystemImpl`, `ProcessManagerImpl`, `NetworkManagerImpl`
3. **Proxy launcher** (L80): `ProxyProcessLauncherImpl(processManager)`
4. **ProxyManagerFactory** (L83–87): receives `proxyProcessLauncher`, `fileSystem`, `logger`
5. **SessionStoreFactory** (L89)
6. **AdapterRegistry** (L94–99): configured with `validateOnRegister: false`, `allowOverride: false`, `enableDynamicLoading: true`
7. **Bundled adapters** (L101–115): reads `globalThis.__DEBUG_MCP_BUNDLED_ADAPTERS__`, registers each synchronously; handles async registration results gracefully
8. **Container-mode adapters** (L119–149): if `process.env.MCP_CONTAINER === 'true'`, fire-and-forget dynamic `import()` for 7 language adapters (mock, python, javascript, ruby, rust, go, java) via URL constructed from `import.meta.url`; skips disabled languages via `isLanguageDisabled()`

## Internal Types & Constants

### `BundledAdapterEntry` type (L32–35)
`{ language: string; factoryCtor: new () => IAdapterFactory }` — shape of entries in the global bundled adapters array.

### `BUNDLED_ADAPTERS_KEY` constant (L36)
`'__DEBUG_MCP_BUNDLED_ADAPTERS__'` — key on `globalThis` for pre-registered bundled adapter entries; enables external bundles to inject adapters before the container initializes.

## Architectural Decisions
- **Fire-and-forget dynamic imports** in container mode (L127–139): adapter registration failures are silently swallowed; this is intentional to avoid blocking startup.
- **`validateOnRegister: false`** (L95): adapter validation deferred to instance creation time, not registration time.
- **`allowOverride: false`** (L96): adapters cannot be re-registered once set.
- **`enableDynamicLoading: true`** (L97): AdapterRegistry can discover adapters on-demand.
- **`globalThis` injection point** (L101): allows external bundlers/hosts to pre-populate adapter factories before `createProductionDependencies` is called.
- **`AdapterRegistryConfig & { enableDynamicLoading?: boolean }`** cast (L94): `enableDynamicLoading` is an extension property not in the base `AdapterRegistryConfig` type, added via intersection.

## Dependencies
| Import | Source |
|---|---|
| `ContainerConfig` | `./types.js` |
| `createLogger` | `../utils/logger.js` |
| `IFileSystem`, `IProcessManager`, `INetworkManager`, `ILogger`, `IEnvironment`, `IAdapterFactory`, `IProxyProcessLauncher`, `IAdapterRegistry`, `AdapterRegistryConfig` | `@debugmcp/shared` |
| `FileSystemImpl`, `ProcessManagerImpl`, `NetworkManagerImpl`, `ProxyProcessLauncherImpl` | `../implementations/index.js` |
| `ProcessEnvironment` | `../implementations/environment-impl.js` |
| `ISessionStoreFactory`, `SessionStoreFactory` | `../factories/session-store-factory.js` |
| `ProxyManagerFactory`, `IProxyManagerFactory` | `../factories/proxy-manager-factory.js` |
| `AdapterRegistry` | `../adapters/adapter-registry.js` |
| `isLanguageDisabled` | `../utils/language-config.js` |
