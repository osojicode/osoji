# packages\adapter-go\src\go-adapter-factory.ts
@source-hash: ac440ee53e7b99ef
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:45Z

## GoAdapterFactory (L18-103)

Factory class implementing `IAdapterFactory` for creating Go debug adapter instances. Serves as the dependency-injection entry point for Go debugging support using the Delve (`dlv`) debugger.

### Key Class: `GoAdapterFactory` (L18-103)
Implements `IAdapterFactory` interface from `@debugmcp/shared`. Three public methods:

**`createAdapter(dependencies)` (L22-24)**
Instantiates and returns a new `GoDebugAdapter` by forwarding `AdapterDependencies` directly. Stateless factory method.

**`getMetadata()` (L29-42)**
Returns static `AdapterMetadata` object describing the Go adapter:
- `language`: `DebugLanguage.GO`
- `displayName`: `'Go'`
- `version`: `'0.1.0'`
- `minimumDebuggerVersion`: `'0.17.0'` (Delve minimum)
- `fileExtensions`: `['.go']`
- Includes a base64-encoded SVG Go gopher icon (L40)

**`validate()` (L47-102)**
Async environment validation. Checks:
1. Go executable presence via `findGoExecutable()` (L57)
2. Go version ≥ 1.18 via `getGoVersion()` (L60-68); adds error if older, warning if undetectable
3. Delve executable via `findDelveExecutable()` (L72)
4. Delve version via `getDelveVersion()` (L73)
5. Delve DAP mode support via `checkDelveDapSupport()` (L75-79); adds error if unsupported, including stderr hint

Returns `FactoryValidationResult` with:
- `valid`: true only if `errors` array is empty
- `errors`, `warnings` arrays
- `details` object: `goPath`, `goVersion`, `dlvPath`, `dlvVersion`, `platform` (`process.platform`), `arch` (`process.arch`), `timestamp` (ISO string)

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage`
- `./go-debug-adapter.js`: `GoDebugAdapter` — the concrete adapter being constructed
- `./utils/go-utils.js`: `findGoExecutable`, `findDelveExecutable`, `getGoVersion`, `getDelveVersion`, `checkDelveDapSupport`

### Architecture Notes
- Stateless factory; no instance fields
- Validation logic is environment-dependent (invokes shell utilities via go-utils)
- Error vs. warning distinction: missing/incompatible tooling → `errors`; ambiguous/undetectable state → `warnings`
- DAP support error message includes the exact `go install` command to fix the issue (L78, L81)
- Inner try/catch (L71-82) isolates Delve failures from Go executable failures so partial details can still be reported