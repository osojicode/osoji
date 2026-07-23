# packages\adapter-javascript\src\utils\config-transformer.ts
@source-hash: 95954345609c7f68
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:53Z

## Purpose
Provides synchronous, no-throw helper utilities for transforming JavaScript/TypeScript launch configurations. Focuses on filesystem-based heuristics to detect ESM projects and tsconfig path aliases, plus determining outFiles patterns for js-debug.

## Key Symbols

### `defaultFileSystem` (L13) — `FileSystem` (module-level variable)
Mutable singleton holding the active `FileSystem` implementation. Defaults to `new NodeFileSystem()`. Overridable via `setDefaultFileSystem` for testing.

### `setDefaultFileSystem(fileSystem)` (L19–21) — exported function
Replaces the module-level `defaultFileSystem`. Intended for test injection of mock filesystems.

### `determineOutFiles(userOutFiles?)` (L28–33) — exported function
Returns user-supplied outFiles array unchanged if non-empty; otherwise returns the default glob pattern `['**/*.js', '!**/node_modules/**']`. Used to provide sensible defaults for js-debug's `outFiles` launch config property.

### `safeJsonParse<T>(text)` (L38–44) — internal function
Generic JSON.parse wrapper that returns `undefined` on any parse error. Used internally by `isESMProject` and `hasTsConfigPaths` to avoid throwing on malformed config files.

### `PkgJson` (L46) — internal type alias
Shape: `{ type?: string }`. Represents the relevant subset of `package.json`.

### `TsConfig` (L47) — internal type alias
Shape: `{ compilerOptions?: { module?: string; paths?: Record<string, string[] | string> } }`. Represents the relevant subset of `tsconfig.json`.

### `isESMProject(programPath, cwd?, fileSystem?)` (L56–113) — exported function
Heuristically determines whether a project uses ESM. Detection order:
1. **Extension check** (L62–67): returns `true` if `programPath` has `.mjs` or `.mts` extension (case-insensitive).
2. **package.json check** (L75–88): looks for `"type": "module"` in `package.json` within `programDir` and `cwd`.
3. **tsconfig.json check** (L91–108): looks for `compilerOptions.module` equal to `"esnext"` or `"nodenext"` (case-insensitive) in `tsconfig.json` within `programDir` and `cwd`.

Returns `false` on any unhandled error (outer catch at L109–111 enforces no-throw policy). Accepts an optional injectable `FileSystem` (defaults to `defaultFileSystem`).

### `hasTsConfigPaths(cwdOrProgramDir, fileSystem?)` (L119–143) — exported function
Checks whether a `tsconfig.json` in the given directory has non-empty `compilerOptions.paths`. Returns `true` only when `paths` is a non-empty object. Fully no-throw; ignores all filesystem and parse errors. Accepts an optional injectable `FileSystem`.

## Architecture & Patterns
- **Dependency injection for filesystem**: All filesystem-touching functions accept an optional `FileSystem` parameter, enabling unit testing without real disk access. The module-level `defaultFileSystem` (overridable via `setDefaultFileSystem`) provides the production default.
- **No-throw policy**: Every exported function wraps its logic in try/catch and returns a safe default on failure — consistent with cheap fs-check usage in launch config pipelines.
- **Checks both `programDir` and `cwd`**: `isESMProject` builds a `dirsToCheck` array from both locations (L70–72), avoiding duplication if they resolve to the same path (though no dedup is performed; this is benign since both checks are idempotent reads).
- **`@debugmcp/shared`** provides `FileSystem` interface and `NodeFileSystem` concrete implementation.

## Dependencies
- `path` (Node stdlib) — path resolution and extension extraction
- `@debugmcp/shared` — `FileSystem` interface, `NodeFileSystem` implementation