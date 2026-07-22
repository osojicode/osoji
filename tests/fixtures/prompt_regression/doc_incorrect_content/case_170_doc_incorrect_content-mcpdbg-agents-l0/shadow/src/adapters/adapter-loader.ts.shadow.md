# src\adapters\adapter-loader.ts
@source-hash: d083d0be6020642c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:35Z

## Purpose
Dynamically loads language-specific debug adapter packages at runtime, with caching, fallback resolution strategies, and availability metadata. Acts as a registry/factory resolver for `IAdapterFactory` instances.

## Key Interfaces

### `ModuleLoader` (L7-9)
Abstraction for dynamic module loading. Single method `load(modulePath: string): Promise<Record<string, unknown>>`. Injected into `AdapterLoader` to enable testability (mock the loader without touching the filesystem).

### `AdapterMetadata` (L11-16)
Data shape returned by `listAvailableAdapters()`. Fields: `name`, `packageName`, `description?`, `installed` (boolean reflecting runtime loadability).

## Core Class: `AdapterLoader` (L18-177)

### Constructor (L23-26)
Accepts optional `logger` (WinstonLogger) and `moduleLoader` (ModuleLoader). Defaults: `createLogger('AdapterLoader')` and a default loader using dynamic `import()`.

### `loadAdapter(language: string): Promise<IAdapterFactory>` (L42-120)
Primary method. Resolution strategy:
1. **Cache check** (L44-46): Returns cached `IAdapterFactory` if previously loaded.
2. **Primary import** (L57): Attempts `moduleLoader.load(packageName)` where `packageName = @debugmcp/adapter-${language}`.
3. **Fallback URLs** (L60-87): If primary fails, tries two URL paths via `getFallbackModulePaths()`:
   - `../../node_modules/@debugmcp/adapter-${lang}/dist/index.js` (relative to `import.meta.url`)
   - `../../packages/adapter-${lang}/dist/index.js`
   - Each URL also attempted via `createRequire` (CJS/bundled context compatibility, L71-81).
4. **Factory extraction** (L94-99): Looks up `${Capitalized}AdapterFactory` named export in the loaded module, instantiates it with `new`.
5. **Error handling** (L104-118): Distinguishes `ERR_MODULE_NOT_FOUND`/`MODULE_NOT_FOUND` (adapter not installed, suggests `npm install`) from other errors (rebuild suggestion).

### `isAdapterAvailable(language: string): Promise<boolean>` (L125-132)
Wraps `loadAdapter` — returns `true` on success, `false` on any error. Side effect: populates cache on success.

### `listAvailableAdapters(): Promise<AdapterMetadata[]>` (L137-157)
Returns metadata for 8 known adapters: `mock`, `python`, `javascript`, `ruby`, `rust`, `go`, `java`, `dotnet`. Probes each with `isAdapterAvailable()` to set `installed` flag. **Note**: This performs 8 sequential `loadAdapter` calls; can be slow.

### Private Helpers
- `createDefaultModuleLoader()` (L28-37): Returns `ModuleLoader` wrapping `import()` with `/* webpackIgnore: true */`.
- `getPackageName(language)` (L159-161): `@debugmcp/adapter-${language.toLowerCase()}`.
- `getFallbackModulePaths(language)` (L164-170): Generates 2 fallback URL strings using `import.meta.url` as anchor.
- `getFactoryClassName(language)` (L172-176): Capitalizes first letter and appends `AdapterFactory` (e.g., `python` → `PythonAdapterFactory`).

## Key Patterns / Architectural Notes
- **Multi-stage fallback resolution**: package name → node_modules path → monorepo packages path → createRequire — supports both published npm installs and monorepo dev setups.
- **Cache key is the language string** (not the package name). Case-sensitive at cache level but all path generation uses `.toLowerCase()`.
- **Factory class naming convention**: `${Capitalized}AdapterFactory` — adapter packages must export this exact name.
- **`webpackIgnore` comment** (L32): Prevents bundlers from statically analyzing the dynamic import.
- **`import.meta.url`** is used as the resolution anchor for fallback paths, making them relative to this file's location at runtime.
