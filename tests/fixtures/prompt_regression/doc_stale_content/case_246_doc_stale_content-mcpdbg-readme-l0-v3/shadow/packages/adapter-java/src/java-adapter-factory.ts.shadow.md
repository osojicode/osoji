# packages\adapter-java\src\java-adapter-factory.ts
@source-hash: f3aecb9df27efe65
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:21Z

## JavaAdapterFactory (L17-93)

Factory class implementing `IAdapterFactory` for creating Java debug adapter instances backed by the JDI bridge (`JdiDapServer`).

### Primary Responsibility
Instantiates `JavaDebugAdapter` instances and validates the Java debugging environment (JDK availability, JDI bridge compilation status).

### Key Class: `JavaAdapterFactory` (L17-93)
Implements `IAdapterFactory` from `@debugmcp/shared`. Three public methods:

- **`createAdapter(dependencies)`** (L21-23): Constructs and returns a new `JavaDebugAdapter` instance, passing through `AdapterDependencies` unchanged.
- **`getMetadata()`** (L28-40): Returns static `AdapterMetadata` with:
  - `language`: `DebugLanguage.JAVA`
  - `displayName`: `'Java'`
  - `version`: `'0.2.0'`
  - `minimumDebuggerVersion`: `'0.18.0'`
  - `fileExtensions`: `['.java']`
  - Inline base64-encoded SVG Java icon
- **`validate()`** (L45-92): Async environment validation. Checks two prerequisites:
  1. **JDI bridge**: Calls `resolveJdiBridgeClassDir()` (L53) — missing bridge is a **warning** (not error), suggesting `pnpm --filter @debugmcp/adapter-java run build:adapter`
  2. **Java executable**: Calls `findJavaExecutable()` (L62) + `getJavaVersion()` (L63). Missing Java is an **error**. Java < 21 is a **warning**. Version parsing handles both modern (`17.0.1` → 17) and legacy (`1.8.0_301` → 8) version formats (L67-73).
  Returns `FactoryValidationResult` with `valid: errors.length === 0`, errors, warnings, and diagnostic details (javaPath, javaVersion, jdiBridgeDir, platform, arch, timestamp).

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage`
- `./java-debug-adapter.js`: `JavaDebugAdapter` — instantiated in `createAdapter`
- `./utils/java-utils.js`: `findJavaExecutable`, `getJavaVersion` — used in `validate`
- `./utils/jdi-resolver.js`: `resolveJdiBridgeClassDir` — used in `validate`

### Architectural Notes
- Missing JDI bridge yields a warning (non-fatal), allowing the factory to be instantiated without a compiled bridge; adapter creation may still fail later at runtime.
- Missing Java is an error (fatal), making `validate()` return `valid: false`.
- `validate()` result `details` object includes runtime environment info (`process.platform`, `process.arch`, `new Date().toISOString()`) for diagnostics.