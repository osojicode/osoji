# src\adapters\adapter-loader.ts
@source-hash: d083d0be6020642c
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:16Z

## adapter-loader.ts

Dynamically loads language-specific debug adapter packages at runtime, with caching, fallback resolution strategies, and availability introspection.

### Interfaces

**`ModuleLoader` (L7-9)**
Abstraction over dynamic `import()`, injectable for testing. Single method `load(modulePath): Promise<Record<string, unknown>>`.

**`AdapterMetadata` (L11-16)**
Describes a known adapter: `name`, `packageName`, `description?`, `installed` (boolean, checked at runtime).

### Class: `AdapterLoader` (L18-177)

**Constructor (L23-26):** Accepts optional `logger` (Winston) and `moduleLoader`. Defaults to `createLogger('AdapterLoader')` and a webpack-ignore-annotated dynamic `import()` loader.

**`loadAdapter(language: string): Promise<IAdapterFactory>` (L42-120)**
Core method. Resolution order:
1. Cache lookup by `language` key (L44-46)
2. Primary import by package name (e.g., `@debugmcp/adapter-python`) (L57)
3. Fallback to two URLs in order (L60, L166-169):
   - `../../node_modules/@debugmcp/adapter-<lang>/dist/index.js`
   - `../../packages/adapter-<lang>/dist/index.js`
4. For each URL fallback, also tries `createRequire` + `fileURLToPath` for CJS/bundled contexts (L71-81)
5. Instantiates factory via `new FactoryClass()` where class name is `<Capitalized>AdapterFactory` (L99)
6. On `ERR_MODULE_NOT_FOUND`/`MODULE_NOT_FOUND`: warns and throws with install instructions (L110-113)
7. On other errors: logs error and throws with reinstall suggestion (L115-117)

**`isAdapterAvailable(language: string): Promise<boolean>` (L125-132)**
Calls `loadAdapter`, returns `true`/`false`. Side effect: caches successfully loaded adapters.

**`listAvailableAdapters(): Promise<AdapterMetadata[]>` (L137-157)**
Iterates 8 known adapters (mock, python, javascript, ruby, rust, go, java, dotnet), checks each via `isAdapterAvailable`, returns full metadata list with `installed` flags.

**Private helpers:**
- `getPackageName(language)` (L159-161): Returns `@debugmcp/adapter-<language.toLowerCase()>`
- `getFallbackModulePaths(language)` (L164-170): Returns 2 fallback URL strings using `import.meta.url`
- `getFactoryClassName(language)` (L172-176): Returns `<Capitalized>AdapterFactory`
- `createDefaultModuleLoader()` (L28-37): Returns inline object with webpack-ignore dynamic import

### Key Patterns
- **Factory class naming convention:** `PythonAdapterFactory`, `JavascriptAdapterFactory`, etc. — exact match required in loaded module exports.
- **Cache key:** raw `language` string as passed (not normalized to lowercase before cache check, but package name derives from `toLowerCase()`).
- **Monorepo-aware fallbacks:** Two-path fallback supports both installed (`node_modules`) and local development (`packages/`) layouts.
- **`IAdapterFactory` contract:** All loaded factories must implement `@debugmcp/shared`'s `IAdapterFactory` interface.

### Dependencies
- `@debugmcp/shared`: `IAdapterFactory` interface
- `winston`: Logger type (injected)
- `../utils/logger.js`: `createLogger` factory
- `module` (Node.js): `createRequire` for CJS fallback
- `url` (Node.js): `fileURLToPath` for URL-to-path conversion