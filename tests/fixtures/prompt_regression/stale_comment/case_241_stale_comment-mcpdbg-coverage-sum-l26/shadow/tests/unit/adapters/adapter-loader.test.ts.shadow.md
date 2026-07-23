# tests\unit\adapters\adapter-loader.test.ts
@source-hash: 7d476402a4cd6579
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:01Z

## Unit Tests for `AdapterLoader`

Tests the `AdapterLoader` class from `src/adapters/adapter-loader.ts`, covering dynamic loading, caching, fallback resolution, and error handling for the adapter plugin system.

### Test Setup (L24-48)
- **`adapterLoader`**: Instance of `AdapterLoader` constructed with `mockLogger` and `mockModuleLoader` before each test.
- **`mockLogger`**: Inline object with `debug`, `info`, `warn`, `error` vi.fn() spies — passed as logger to `AdapterLoader`.
- **`mockModuleLoader`**: Object implementing `ModuleLoader` interface with a single `load: vi.fn()` method.
- Cache is explicitly cleared between tests via `(adapterLoader as any).cache.clear()` (L42).
- `vi.mock('module', ...)` (L13-15) replaces `createRequire` from Node's `module` package globally.

### Helper
- **`createMockAdapterFactory(name)`** (L18-22): Returns a factory-shape object with `getMetadata()`, `createAdapter`, and `validate` (resolves `{ valid: true }`). Used as the return value of mock factory class constructors.

---

### `loadAdapter` Tests (L50-229)

| Test | Description |
|------|-------------|
| L51-75 | Happy path: loads `'python'` → `@debugmcp/adapter-python`, instantiates `PythonAdapterFactory`, logs info, caches result (second call does not re-invoke loader). |
| L77-102 | Fallback URL path: first load attempt fails, second attempt matches `node_modules/@debugmcp/adapter-mock`; expects `debug` log containing `'Primary import failed for @debugmcp/adapter-mock, trying fallback URL'`. |
| L104-123 | `createRequire` fallback: all `moduleLoader.load` attempts rejected; `createRequire` mock returns a `require` that returns the module; expects `debug` log `'Loaded via createRequire from'`. |
| L125-145 | Not-installed error: all load paths throw `ERR_MODULE_NOT_FOUND` / `MODULE_NOT_FOUND`; expects rejection with install hint message; `mockLogger.warn` called. |
| L147-160 | Factory class missing: module resolves but lacks expected factory key (`PythonAdapterFactory`); expects rejection `'Factory class PythonAdapterFactory not found in @debugmcp/adapter-python'`. |
| L162-176 | Generic error: all paths throw `'Network error'`; expects rejection matching `/Failed to load adapter for 'python' from package '@debugmcp\/adapter-python'/`; `mockLogger.error` called. |
| L178-202 | Happy path for `'javascript'` → `JavascriptAdapterFactory` (mirrors python test). |
| L204-229 | Fallback URL for `'javascript'`; same pattern as mock fallback test. |

---

### `isAdapterAvailable` Tests (L232-271)

| Test | Description |
|------|-------------|
| L233-242 | Returns `true` when `loadAdapter` succeeds. |
| L244-255 | Returns `false` when all load attempts fail. |
| L257-271 | Cache: after one successful load, `mockModuleLoader.load` called only once across two `isAdapterAvailable` calls. |

---

### `listAvailableAdapters` Tests (L274-412)

- **L275-360**: Full listing test — 8 adapters expected: `python`, `mock`, `javascript`, `ruby`, `rust`, `go`, `java`, `dotnet`. Each entry shape: `{ name, packageName, description, installed }`. Only `python` is `installed: true` (mocked via module loader); all others are `false`.
- **L362-375**: Spies on `isAdapterAvailable` to return `true` only for `'javascript'`; verifies `installed: true` for that adapter.
- **L379-412** (top-level `it`, outside `describe`): Monorepo fallback — primary import fails with `ERR_MODULE_NOT_FOUND`, but fallback path containing `packages/adapter-javascript/dist/index.js` resolves; `listAvailableAdapters` returns `javascript` with `installed: true`.

---

### Private Method Tests (L414-434)

Directly accesses private methods via bracket notation:
- `getPackageName('python')` → `'@debugmcp/adapter-python'`; `getPackageName('Mock')` → lowercased `'@debugmcp/adapter-mock'` (L417-418).
- `getFactoryClassName('python')` → `'PythonAdapterFactory'`; `'mock'` → `'MockAdapterFactory'`; `'javascript'` → `'JavascriptAdapterFactory'` (L422-426).
- `getFallbackModulePaths('python')` → array of length 2: one containing `node_modules/@debugmcp/adapter-python`, one containing `packages/adapter-python` (L429-433).

---

### Caching Tests (L436-461)

- Separate cache entries per language: `python` and `mock` load independently, return distinct factory instances, and both are cached (four `loadAdapter` calls → two `moduleLoader.load` invocations).

---

### Adapter Package Naming Convention
Package name: `@debugmcp/adapter-{language}` (lowercase).
Factory class name: `{Language}AdapterFactory` (title-case, no special handling for multi-word like `javascript`).

### Known Adapters (as of this test file)
`python`, `mock`, `javascript`, `ruby`, `rust`, `go`, `java`, `dotnet` — 8 total (verified at L295).
