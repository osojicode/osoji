# packages\mcp-debugger\src\batteries-included.ts
@source-hash: 1d8d8bc6c5cd4195
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:01Z

## Purpose

Side-effect-only module that statically imports all language adapter factories to force esbuild bundling, then registers them into a global registry (`globalThis.__DEBUG_MCP_BUNDLED_ADAPTERS__`) for runtime discovery. Designed for the "batteries-included" npx CLI distribution.

## Key Elements

### `BundledAdapterEntry` interface (L20-23)
Internal shape for registry entries: `{ language: union-string-literal, factoryCtor: new () => IAdapterFactory }`. Typed as a constructor (not instance) so callers can instantiate adapters on demand.

### `GLOBAL_KEY` constant (L25)
String key `'__DEBUG_MCP_BUNDLED_ADAPTERS__'` used to store/read the adapter registry on `globalThis`. Acts as the cross-module contract for adapter discovery.

### `adapters` array (L27-36)
File-local array mapping all 8 supported languages to their factory constructors:
- `javascript` → `JavascriptAdapterFactory`
- `python` → `PythonAdapterFactory`
- `mock` → `MockAdapterFactory`
- `ruby` → `RubyAdapterFactory`
- `go` → `GoAdapterFactory`
- `rust` → `RustAdapterFactory`
- `java` → `JavaAdapterFactory`
- `dotnet` → `DotnetAdapterFactory`

### Global registration logic (L38-48)
Module-level side effect executed on import:
- **Merge path (L39-45):** If `globalThis[GLOBAL_KEY]` already exists as an array (e.g., module loaded twice or multiple bundles), new adapters are appended by language deduplication using a `Set`.
- **Init path (L47):** If no prior registry exists, sets `globalThis[GLOBAL_KEY]` to a shallow copy of `adapters`.

## Architectural Decisions

- **No exports** (L51): Only `export {}` to satisfy TypeScript module requirements. All functionality is via side effects.
- **Global registry pattern**: Uses `globalThis` (not a module singleton) to survive module boundary issues in bundled environments where multiple copies of this file might be evaluated.
- **Deduplication by language string**: Prevents duplicate factories if the module is evaluated more than once (e.g., in monorepo scenarios with multiple resolutions).
- **Import-for-bundling**: All adapter imports exist solely to force the bundler (esbuild) to include them in the output; the imported values are only stored as constructors in `adapters`.

## Dependencies

| Import | Role |
|--------|------|
| `@debugmcp/adapter-javascript` | JavaScript/Node.js debug adapter |
| `@debugmcp/adapter-python` | Python debug adapter |
| `@debugmcp/adapter-mock` | Mock adapter for testing |
| `@debugmcp/adapter-ruby` | Ruby debug adapter |
| `@debugmcp/adapter-go` | Go debug adapter |
| `@debugmcp/adapter-rust` | Rust debug adapter |
| `@debugmcp/adapter-java` | Java debug adapter |
| `@debugmcp/adapter-dotnet` | .NET debug adapter |
| `@debugmcp/shared` | `IAdapterFactory` interface (type-only) |

## Usage Pattern

Import this file once at CLI entry to register all adapters globally. Other code reads `globalThis.__DEBUG_MCP_BUNDLED_ADAPTERS__` to discover available adapters without needing direct imports of each adapter package.