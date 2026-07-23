# packages\adapter-dotnet\src\DotnetAdapterFactory.ts
@source-hash: 5d0f0a0425282a52
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:43Z

## DotnetAdapterFactory (L18-69)

Factory class implementing `IAdapterFactory` for creating .NET debug adapter instances backed by `netcoredbg`. Used as a dependency-injected factory in the adapter plugin system.

### Key Class

**`DotnetAdapterFactory`** (L18-69) — implements `IAdapterFactory` with three methods:
- **`createAdapter(dependencies)`** (L22-24): Instantiates and returns a `DotnetDebugAdapter` by forwarding `AdapterDependencies`.
- **`getMetadata()`** (L29-41): Returns a static `AdapterMetadata` object describing the adapter — language tag `DebugLanguage.DOTNET`, display name `.NET/C#`, version `0.2.0`, supported file extensions `['.cs', '.vb', '.fs']`, and an embedded base64 SVG icon.
- **`validate()`** (L46-68): Async environment validation. Calls `findNetcoredbgExecutable()` to locate the `netcoredbg` binary; on failure, captures the error message into `errors[]`. Returns a `FactoryValidationResult` with `valid: errors.length === 0`, plus `details` including `debuggerPath`, the string `'netcoredbg'` as `backend`, `process.platform`, and a timestamp.

### Dependencies
- `DotnetDebugAdapter` (same package, `./DotnetDebugAdapter.js`) — the concrete adapter implementation created by this factory.
- `findNetcoredbgExecutable` (`./utils/dotnet-utils.js`) — async utility that resolves the path to the `netcoredbg` executable or throws on failure.
- `IAdapterFactory`, `IDebugAdapter`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage` — all imported from `@debugmcp/shared`.

### Architectural Notes
- Follows an abstract factory / plugin pattern: consumers call `createAdapter()` and `validate()` through the `IAdapterFactory` interface, never referencing `DotnetAdapterFactory` directly.
- `validate()` is the only async method; `createAdapter()` and `getMetadata()` are synchronous.
- Metadata version `'0.2.0'` is hardcoded and must be updated manually on releases.
- `validate()` captures the thrown `Error.message` (or a fallback string) — no re-throw, so validation failures are surfaced only via `FactoryValidationResult.errors`.
