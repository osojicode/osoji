# tests\core\unit\adapters\debug-adapter-interface.test.ts
@source-hash: 08d5b265dde3b91e
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:24Z

## Purpose
Unit tests for the `debug-adapter-interface` module exported from `@debugmcp/shared`. Validates enum values, error class behavior, and interface shape conformance for all types in the debug adapter interface contract.

## Test Structure

### `AdapterState` enum tests (L25–40)
- Verifies 7 state string values: `uninitialized`, `initializing`, `ready`, `connected`, `debugging`, `disconnected`, `error`
- Count assertion at L36–39 acts as a regression guard against enum additions

### `AdapterErrorCode` enum tests (L42–75)
- 13 error codes grouped into 4 categories: environment (4), connection (3), protocol (2), runtime (3), plus `UNKNOWN_ERROR`
- All codes are uppercase string literals matching their key names (e.g., `'CONNECTION_FAILED'`)
- Count assertion at L71–74 guards against additions

### `DebugFeature` enum tests (L77–105)
- 20 camelCase string values mapping DAP capability names
- Count assertion at L101–104 guards against additions

### `AdapterError` class tests (L107–140)
- Constructor: `(message: string, code: AdapterErrorCode, recoverable?: boolean)`
- Default `recoverable` is `false` (L127–131)
- Extends native `Error`; `name` property set to `'AdapterError'` (L116)
- Stack trace includes class name and message (L133–139)

### Interface shape tests (L142–483)
- **`ValidationResult`** (L143–190): `{ valid, errors: ValidationError[], warnings: ValidationWarning[] }`
- **`ValidationError`** (L157–161): `{ code: string, message: string, recoverable: boolean }`
- **`ValidationWarning`** (L175–178): `{ code: string, message: string }`
- **`DependencyInfo`** (L192–216): required `name`, `required`; optional `version`, `installCommand`
- **`AdapterCommand`** (L218–244): required `command`, `args`; optional `env: Record<string, string>`
- **`AdapterConfig`** (L246–285): required `sessionId`, `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath`, `launchConfig`; optional `scriptArgs`
- **`GenericLaunchConfig`** (L287–313): all-optional `stopOnEntry`, `justMyCode`, `env`, `cwd`, `args`; supports empty object `{}`
- **`LanguageSpecificLaunchConfig`** (L315–329): extends `GenericLaunchConfig` with arbitrary additional string-keyed fields (accessed via bracket notation at L325–327)
- **`FeatureRequirement`** (L332–366): `{ type: 'dependency' | 'version' | 'configuration', description: string, required: boolean }`
- **`AdapterCapabilities`** (L368–455): large all-optional flags object; supports `exceptionBreakpointFilters: ExceptionBreakpointFilter[]`, `completionTriggerCharacters: string[]`, `supportedChecksumAlgorithms` (cast via `as any` at L450)
- **`ExceptionBreakpointFilter`** (L457–483): required `filter`, `label`; optional `description`, `default`, `supportsCondition`, `conditionDescription`

### Error handling pattern tests (L486–513)
- Verifies category-specific error code assignment
- Validates recoverable vs. fatal error distinction

### Type safety tests (L515–530)
- Confirms enum values are contained within their respective `Object.values()` sets

## Key Dependencies
- All tested symbols imported from `@debugmcp/shared` (L6–22); this is the sole production dependency
- Test runner: `vitest` (L5)

## Architectural Notes
- Tests serve as living documentation of the `@debugmcp/shared` interface contract
- Count assertions (L36–39, L71–74, L101–104) function as CI guards: adding enum members without updating tests will cause failures
- `LanguageSpecificLaunchConfig` allows arbitrary extra fields beyond `GenericLaunchConfig` (demonstrated by bracket access pattern at L325–327)
- `supportedChecksumAlgorithms` uses `as any` cast (L450), suggesting the enum type for checksum algorithms is not directly importable or is intentionally loose in tests
