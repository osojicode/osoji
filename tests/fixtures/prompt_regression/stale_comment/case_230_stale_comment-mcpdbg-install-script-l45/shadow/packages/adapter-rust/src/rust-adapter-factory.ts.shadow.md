# packages\adapter-rust\src\rust-adapter-factory.ts
@source-hash: 2ee8e39e11353a9d
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:49Z

## RustAdapterFactory (L17-93)

Factory class implementing `IAdapterFactory` for creating Rust debug adapter instances. Serves as the dependency-injection entry point for the Rust adapter package.

### Key Class: `RustAdapterFactory` (L17-93)
Implements `IAdapterFactory` interface from `@debugmcp/shared`. Three public methods:

**`createAdapter(dependencies)` (L21-23):** Instantiates and returns a `RustDebugAdapter` wrapping the provided `AdapterDependencies`. Synchronous.

**`getMetadata()` (L28-40):** Returns static `AdapterMetadata` object:
- `language`: `DebugLanguage.RUST`
- `displayName`: `'Rust'`
- `version`: `'0.1.0'`
- `description`: `'Debug Rust applications using CodeLLDB'`
- `fileExtensions`: `['.rs']`
- `minimumDebuggerVersion`: `'1.0.0'`
- `documentationUrl`: `'https://github.com/debugmcp/mcp-debugger/docs/rust'`
- `icon`: base64-encoded SVG

**`validate()` (L45-92):** Async environment validation. Checks:
1. **CodeLLDB** (L54-60): Calls `resolveCodeLLDBExecutable()` — pushes error if not found, otherwise records path and version via `getCodeLLDBVersion()`. CodeLLDB absence is a hard error (`valid: false`).
2. **Cargo** (L63-68): Calls `checkCargoInstallation()` — pushes warning (not error) if absent, otherwise records version via `getCargoVersion()`. Cargo absence is non-blocking.
3. **Host triple** (L70-76): Calls `getRustHostTriple()` — if MSVC toolchain detected (`/-pc-windows-msvc/i`), pushes warning recommending GNU toolchain.

Returns `FactoryValidationResult` with:
- `valid`: `true` only if `errors` is empty (missing CodeLLDB = invalid)
- `errors`, `warnings` arrays
- `details`: `{ codelldbPath, codelldbVersion, cargoVersion, hostTriple, platform, arch, timestamp }`

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage`
- `./rust-debug-adapter.js`: `RustDebugAdapter` (instantiated in `createAdapter`)
- `./utils/rust-utils.js`: `checkCargoInstallation`, `getCargoVersion`, `getRustHostTriple`
- `./utils/codelldb-resolver.js`: `resolveCodeLLDBExecutable`, `getCodeLLDBVersion`

### Architectural Notes
- Cargo missing is a **warning** (non-blocking); CodeLLDB missing is an **error** (blocking). This reflects that CodeLLDB is the actual debug engine while Cargo is only needed for building.
- `validate()` uses `|| undefined` pattern (L59, L67) to coerce `null`/falsy string returns to `undefined` for the details object.
- `process.platform` and `process.arch` are captured directly at validation time for environment diagnostics.
