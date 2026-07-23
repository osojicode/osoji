# tests\unit\container\dependencies.test.ts
@source-hash: bc0c9d79750d4409
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:03Z

## Unit Tests: `createProductionDependencies` (Container Dependencies)

Tests the dependency wiring function `createProductionDependencies` from `src/container/dependencies.js`. All external modules are mocked via `vi.mock` at module scope; the SUT is dynamically imported after mocking (L62).

### Test File Structure

**Module-level mock setup (L3–60):**
- `createLoggerMock` (L3–6): Replaces `createLogger` from `src/utils/logger.js`
- Singleton stub instances for all infrastructure (L8–13): `fileSystemInstance`, `processManagerInstance`, `networkManagerInstance`, `proxyProcessLauncherInstance`, `proxyManagerFactoryInstance`, `sessionStoreFactoryInstance`
- `registerMock` / `getSupportedLanguagesMock` (L15–16): Stub `AdapterRegistry` methods
- `AdapterRegistryMock` class (L43–50): Local mock replacing the real `AdapterRegistry`; exposes `.config`, `.register`, `.getSupportedLanguages`
- `isLanguageDisabledMock` (L56): Replaces `isLanguageDisabled` from `src/utils/language-config.js`
- `environmentInstance` (L29): Stub for `ProcessEnvironment`

**`BUNDLED_ADAPTERS_KEY`** = `'__DEBUG_MCP_BUNDLED_ADAPTERS__'` (L64): Global key used to inject bundled adapters into `globalThis` for testing the adapter registration path.

**`beforeEach` (L66–75):** Resets all mocks and deletes `globalThis[BUNDLED_ADAPTERS_KEY]`.
**`afterEach` (L77–79):** Cleans up `globalThis[BUNDLED_ADAPTERS_KEY]`.

### Test Suite: `createProductionDependencies` (L81–176)

**Test 1 — Core service wiring (L82–115):**
- Calls `createProductionDependencies({ logLevel, logFile, loggerOptions })`
- Asserts `createLogger` called with name `'debug-mcp'` and merged options `{ level, file, ...loggerOptions }`
- Asserts returned `dependencies` object contains all 9 expected fields (fileSystem, processManager, networkManager, logger, environment, proxyProcessLauncher, proxyManagerFactory, sessionStoreFactory, adapterRegistry)
- Asserts `adapterRegistry.config` contains `{ validateOnRegister: false, allowOverride: false, enableDynamicLoading: true }`

**Test 2 — Bundled adapter registration and async failure logging (L117–156):**
- Injects two entries into `globalThis[BUNDLED_ADAPTERS_KEY]` with factory constructors and language keys `'alpha'` and `'beta'`
- First `register` call resolves normally; second rejects with `Error('boom')`
- Asserts both factories are constructed and `register` is called with `(language, factoryInstance)` pairs
- After `await Promise.resolve()`, asserts `logger.warn` called with message containing `"Failed to register bundled adapter 'beta':"`

**Test 3 — Skip disabled adapters in container environment (L158–176):**
- Stubs `MCP_CONTAINER=true` via `vi.stubEnv`
- `isLanguageDisabledMock` returns `true` for all calls
- Asserts `logger.info` called with message containing `"Skipping bundled adapter 'python'"`
- Asserts `registerMock` never called

### Key Architectural Observations

- **Dynamic import after mocking** (L62): The SUT is imported with `await import(...)` after all `vi.mock` calls are hoisted, ensuring mocks are in place before module initialization.
- **`globalThis` injection pattern**: Bundled adapters are injected via `globalThis[BUNDLED_ADAPTERS_KEY]`, suggesting the production code reads this key at runtime to discover pre-bundled adapter factories.
- **Async error isolation**: The test verifies that async registration failures are caught and logged as warnings rather than thrown.
- **Logger name contract**: The production code creates a logger named `'debug-mcp'` (verified at L89).
- **AdapterRegistry config contract**: The registry must be constructed with `{ validateOnRegister: false, allowOverride: false, enableDynamicLoading: true }` (L110–113).
