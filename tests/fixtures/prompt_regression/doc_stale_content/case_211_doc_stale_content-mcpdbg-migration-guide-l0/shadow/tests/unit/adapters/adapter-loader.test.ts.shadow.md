# tests\unit\adapters\adapter-loader.test.ts
@source-hash: 7d476402a4cd6579
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:45Z

## Unit Tests: AdapterLoader

Tests for the `AdapterLoader` class covering dynamic module loading, caching, fallback mechanisms, and error handling. Located in `tests/unit/adapters/adapter-loader.test.ts`.

### Test Subject
- `AdapterLoader` (from `src/adapters/adapter-loader.ts`) — loaded via `mockModuleLoader` injection

### Test Setup (L24–48)
- `mockLogger`: stub with `debug`, `info`, `warn`, `error` vi.fn() methods
- `mockModuleLoader`: stub implementing `ModuleLoader` interface with a single `.load` vi.fn()
- `AdapterLoader` is instantiated with both mocks at L39
- Cache cleared manually between tests via `(adapterLoader as any).cache.clear()` (L42)
- `vi.mock('module', ...)` at L13–15 mocks Node's built-in `module` package to intercept `createRequire`
- `createMockAdapterFactory(name)` (L18–22): returns a factory stub with `getMetadata`, `createAdapter`, `validate`

### Test Groups

#### `loadAdapter` (L50–230)
- **Successful load + caching** (L51–75): Module loader resolves `@debugmcp/adapter-python` → `PythonAdapterFactory` instantiated, result cached; second call returns same instance without re-loading
- **Fallback URL path** (L77–102): Primary import of `@debugmcp/adapter-mock` fails; fallback path containing `node_modules/@debugmcp/adapter-mock` succeeds; debug log emitted
- **createRequire fallback** (L104–123): All `load` calls rejected; `createRequire` mock returns a require stub that succeeds; debug log "Loaded via createRequire from" emitted
- **Not installed error** (L125–145): All strategies throw `ERR_MODULE_NOT_FOUND` / `MODULE_NOT_FOUND`; rejects with helpful install instruction message `"Install with: npm install @debugmcp/adapter-nonexistent"`; warn logged
- **Missing factory class** (L147–160): Module loads but lacks expected `PythonAdapterFactory` export; rejects with `"Factory class PythonAdapterFactory not found in @debugmcp/adapter-python"`
- **General error** (L162–176): Network error propagates; rejects with pattern matching `"Failed to load adapter for 'python' from package '@debugmcp/adapter-python'"`; error logged
- **JavaScript adapter load + cache** (L178–202): Same as python success case but for `javascript` / `JavascriptAdapterFactory`
- **JavaScript fallback** (L204–229): Same fallback pattern as mock adapter but for `@debugmcp/adapter-javascript`

#### `isAdapterAvailable` (L232–272)
- **Returns true** (L233–241): Adapter loads successfully → `true`
- **Returns false** (L244–255): All load strategies fail → `false` (no throw)
- **Caches successful check** (L257–271): Two calls to `isAdapterAvailable('mock')` → `mockModuleLoader.load` called only once

#### `listAvailableAdapters` (L274–376)
- **Returns 8 adapters** (L275–360): Verifies full list with name, packageName, description, installed fields for: `python`, `mock`, `javascript`, `ruby`, `rust`, `go`, `java`, `dotnet`
- **JavaScript installed:true via spy** (L362–375): Spies on `isAdapterAvailable`; when it returns `true` for `'javascript'`, the list entry shows `installed: true`

#### Monorepo fallback (L378–412, top-level `it` — not nested in a `describe`)
- Primary `@debugmcp/adapter-javascript` import throws `ERR_MODULE_NOT_FOUND`; fallback path containing `packages/adapter-javascript/dist/index.js` succeeds → `installed: true` in list

#### `private methods behavior` (L414–434)
- **`getPackageName`** (L415–418): `'python'` → `'@debugmcp/adapter-python'`; `'Mock'` → `'@debugmcp/adapter-mock'` (lowercased)
- **`getFactoryClassName`** (L421–426): `'python'` → `'PythonAdapterFactory'`; `'mock'` → `'MockAdapterFactory'`; `'javascript'` → `'JavascriptAdapterFactory'`
- **`getFallbackModulePaths`** (L428–433): Returns 2 paths; first contains `node_modules/@debugmcp/adapter-python`, second contains `packages/adapter-python`

#### `caching behavior` (L436–461)
- **Separate cache entries** (L437–460): `python` and `mock` loaded independently; each cached separately; verified via repeated loads

### Key Patterns
- Private method access via `adapterLoader['methodName']` for whitebox testing (L417, 423, 429)
- `vi.mocked(createRequire as any)` pattern used throughout to set up `createRequire` mock behavior (e.g., L114, L138)
- Error codes `'ERR_MODULE_NOT_FOUND'` and `'MODULE_NOT_FOUND'` set on error objects to simulate Node.js module-not-found behavior (L128, L135)
- All `mockModuleLoader.load` typings cast through `Mock` from vitest for `.mockImplementation` access (L57)

### Known Adapter Registry
Tests assert exactly 8 known adapters: `python`, `mock`, `javascript`, `ruby`, `rust`, `go`, `java`, `dotnet` (L295)
