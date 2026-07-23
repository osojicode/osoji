# src\adapters\adapter-registry.ts
@source-hash: eb068091b23bdfe0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:55Z

## AdapterRegistry (`src/adapters/adapter-registry.ts`)

### Primary Purpose
Implements the `IAdapterRegistry` interface — manages lifecycle of debug adapter factories and instances, including registration, creation, auto-dispose, dynamic loading, and singleton access.

---

### Key Symbols

#### `DEFAULT_CONFIG` (L26–32)
Default `AdapterRegistryConfig` values:
- `validateOnRegister: true` — validates factory before storing
- `allowOverride: false` — blocks duplicate language registrations
- `maxInstancesPerLanguage: 10` — per-language instance cap
- `autoDispose: true`, `autoDisposeTimeout: 300000` (5 min)

---

#### `AdapterRegistry` (L37–399) — `extends EventEmitter implements IAdapterRegistry`
Core registry class. All state is private and tracked in Maps.

**Private State:**
- `factories: AdapterFactoryMap` — language → `IAdapterFactory` (L38)
- `activeAdapters: ActiveAdapterMap` — language → `Set<IDebugAdapter>` (L39)
- `disposeTimers: Map<IDebugAdapter, NodeJS.Timeout>` — per-adapter auto-dispose timers (L41)
- `registrationTimestamps: Map<string, Date>` — when each language was registered (L42)
- `loader: AdapterLoader` — used for dynamic adapter discovery/loading (L43)
- `dynamicEnabled: boolean` — opt-in flag; true if `enableDynamicLoading` config passed OR `MCP_CONTAINER=true` env (L45, L51–54)

**Constructor (L47–59):**
- Merges config with `DEFAULT_CONFIG`
- Enables dynamic loading via undocumented `enableDynamicLoading` config field (cast through `unknown`) or `MCP_CONTAINER=true` env
- Registers a no-op `'error'` event handler to prevent unhandled error crashes (L58)

---

### Public Methods

**`register(language, factory): Promise<void>` (L64–82)**
- Throws `DuplicateRegistrationError` if language already registered and `allowOverride` is false
- If `validateOnRegister`, calls `factory.validate()` and throws `FactoryValidationError` on failure
- Emits `'factoryRegistered'` with language and factory metadata

**`unregister(language): boolean` (L87–109)**
- Disposes all active adapters for the language (fire-and-forget, errors emitted as `'error'`)
- Clears dispose timers, removes from `activeAdapters` and `factories`
- Emits `'factoryUnregistered'`; returns `false` if language not found

**`create(language, config): Promise<IDebugAdapter>` (L114–177)**
- Falls back to dynamic loading via `AdapterLoader` if language not registered and `dynamicEnabled`
- Throws `AdapterNotFoundError` if factory missing (uses `listLanguages()` for available list when dynamic)
- Enforces `maxInstancesPerLanguage` limit
- Calls `createDependencies(config)` then `factory.createAdapter(dependencies)` then `adapter.initialize()`
- Tracks instance in `activeAdapters`, sets up auto-dispose if `autoDispose` is true
- Listens for adapter `'disposed'` event to remove from tracking map
- Emits `'adapterCreated'`

**`getSupportedLanguages(): string[]` (L182–184)** — returns languages with registered factories

**`isLanguageSupported(language): boolean` (L189–191)** — checks factories map

**`getAdapterInfo(language): AdapterInfo | undefined` (L196–212)** — merges factory metadata with active instance count and registration timestamp

**`getAllAdapterInfo(): Map<string, AdapterInfo>` (L217–228)** — aggregates `getAdapterInfo` for all factories

**`listLanguages(): Promise<string[]>` (L233–262)**
- Without dynamic: returns `getSupportedLanguages()`
- With dynamic: unions `loader.listAvailableAdapters()` (installed only) with statically registered; swallows loader errors

**`listAvailableAdapters(): Promise<AdapterMetadata[]>` (L267–299)**
- Without dynamic: maps registered languages to minimal `AdapterMetadata` (name, packageName `@debugmcp/adapter-${language}`, installed: true)
- With dynamic: merges `loader.listAvailableAdapters()` with registered set; overrides `installed` to `true` for registered adapters

**`disposeAll(): Promise<void>` (L304–332)**
- Disposes all active adapters concurrently (errors emitted, not thrown)
- Clears all timers, activeAdapters, and factories
- Emits `'registryDisposed'`

**`getActiveAdapterCount(): number` (L337–343)** — sum of all active set sizes

---

### Private Methods

**`createDependencies(config): Promise<AdapterDependencies>` (L348–364)**
- Dynamically imports `createProductionDependencies` from `../container/dependencies.js`
- Constructs log file path from `config.logDir` + `config.sessionId` if both present
- Returns `{ fileSystem, logger, environment, networkManager }` from production deps

**`setupAutoDispose(_language, adapter): void` (L369–390)**
- Listens to `adapter.on('stateChanged')` — schedules dispose timer on `'disconnected'`/`'error'` state
- Cancels timer if state becomes `'connected'` or `'debugging'`

**`clearDisposeTimer(adapter): void` (L392–398)** — clears and removes timer for adapter

---

### Module-Level Singleton (L401–428)

**`registryInstance: AdapterRegistry | null`** (L404) — module-level singleton

**`getAdapterRegistry(config?): AdapterRegistry`** (L409–416)
- Creates instance on first call; ignores config on subsequent calls (emits `console.warn`)

**`resetAdapterRegistry(): Promise<void>`** (L421–428)
- Nullifies singleton and calls `disposeAll()` — primarily for test teardown

---

### Emitted Events
| Event | Payload |
|---|---|
| `'factoryRegistered'` | `(language: string, metadata)` |
| `'factoryUnregistered'` | `(language: string)` |
| `'adapterCreated'` | `(language: string, adapter)` |
| `'registryDisposed'` | none |
| `'error'` | `Error` (swallowed by no-op handler) |

---

### Dynamic Loading Notes
- `enableDynamicLoading` is not typed in `AdapterRegistryConfig`; it's cast via `unknown` (L52) — an intentional escape hatch
- Dynamic mode is activated by `MCP_CONTAINER=true` environment variable (L53)
- `AdapterLoader` handles npm-based discovery and package loading

---

### Dependencies
- `@debugmcp/shared`: `IAdapterRegistry`, `IAdapterFactory`, `IDebugAdapter`, `AdapterConfig`, `AdapterDependencies`, `AdapterInfo`, error classes, map types, config types
- `./adapter-loader.js`: `AdapterLoader`, `AdapterMetadata`
- `../container/dependencies.js` (dynamic import): `createProductionDependencies`
- Node.js `events.EventEmitter`