# packages\shared\src\factories\adapter-factory.ts
@source-hash: a47e35af38792bbe
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:22Z

## AdapterFactory (L25-95)

Abstract base class for debug adapter factories in the shared package. Implements `IAdapterFactory` interface and provides default behavior for metadata access, validation, and core version compatibility checking. Language-specific adapter factories must extend this class and implement `createAdapter`.

### Key Symbols

- **`AdapterFactory`** (L25-95) — `abstract class implements IAdapterFactory`. Constructor accepts `AdapterMetadata` stored as `protected readonly metadata` (L30). Cannot be instantiated directly.

- **`getMetadata()`** (L36-38) — Returns a shallow copy (`{ ...this.metadata }`) of the adapter metadata. Prevents mutation of internal state.

- **`validate()`** (L45-51) — `async`, returns `Promise<FactoryValidationResult>`. Default implementation always returns `{ valid: true, errors: [], warnings: [] }`. Subclasses should override when environment-specific validation is needed.

- **`isCompatibleWithCore(coreVersion: string)`** (L58-65) — Checks if a given core version string meets the adapter's `minimumDebuggerVersion` metadata field. Returns `true` if `minimumDebuggerVersion` is unset; otherwise delegates to `compareVersions`.

- **`compareVersions(version1, version2)`** (L73-86) — `protected`. Parses semver-style strings by splitting on `'.'` and comparing integer parts left-to-right. Missing parts default to `0`. Returns `-1`, `0`, or `1`.

- **`createAdapter(dependencies: AdapterDependencies): IDebugAdapter`** (L94) — `abstract`. Must be implemented by concrete subclasses. Synchronous (no `Promise` return type).

### Architectural Role
- Enforces a consistent factory contract across all language-specific adapter implementations.
- Uses the Template Method pattern: default behaviors in the base class, abstract `createAdapter` for subclass specialization.
- `getMetadata()` returns a spread copy — only a **shallow** copy, so nested objects within `AdapterMetadata` are not deep-cloned.

### Dependencies
- `IDebugAdapter` — interface from `../interfaces/debug-adapter.js`
- `AdapterDependencies`, `IAdapterFactory`, `AdapterMetadata`, `FactoryValidationResult` — types from `../interfaces/adapter-registry.js`