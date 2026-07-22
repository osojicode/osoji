# tests\core\unit\adapters\debug-adapter-interface.test.ts
@source-hash: 08d5b265dde3b91e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:01Z

## Purpose
Unit tests for the `debug-adapter-interface` module exported from `@debugmcp/shared`. Validates enum values and counts, `AdapterError` class construction, and TypeScript interface shape compliance (type-level contracts exercised at runtime via object literals).

## Test Structure

### Top-level suite: `debug-adapter-interface` (L24–531)

#### `AdapterState` enum (L25–40)
- Validates 7 string values: `'uninitialized'`, `'initializing'`, `'ready'`, `'connected'`, `'debugging'`, `'disconnected'`, `'error'`
- Count assertion: exactly 7 states (L36–39)

#### `AdapterErrorCode` enum (L42–75)
- Environment codes (L43–48): `ENVIRONMENT_INVALID`, `EXECUTABLE_NOT_FOUND`, `ADAPTER_NOT_INSTALLED`, `INCOMPATIBLE_VERSION`
- Connection codes (L50–54): `CONNECTION_FAILED`, `CONNECTION_TIMEOUT`, `CONNECTION_LOST`
- Protocol codes (L56–59): `INVALID_RESPONSE`, `UNSUPPORTED_OPERATION`
- Runtime codes (L61–65): `DEBUGGER_ERROR`, `SCRIPT_NOT_FOUND`, `PERMISSION_DENIED`
- Generic code (L67–69): `UNKNOWN_ERROR`
- Count assertion: exactly 13 error codes (L71–74)

#### `DebugFeature` enum (L77–105)
- 20 camelCase feature string values (L79–99), e.g. `'conditionalBreakpoints'`, `'stepBack'`, `'reverseDebugging'`
- Count assertion: exactly 20 features (L101–104)

#### `AdapterError` class (L107–140)
- Extends `Error`; has `.code` (`AdapterErrorCode`), `.recoverable` (boolean, defaults `false`), `.name` (`'AdapterError'`)
- Stack trace contains class name and message (L133–139)
- Constructor: `(message, code, recoverable?)` — 3rd arg defaults to `false`

#### `ValidationResult` / `ValidationError` / `ValidationWarning` (L143–190)
- `ValidationResult`: `{ valid: boolean, errors: ValidationError[], warnings: ValidationWarning[] }`
- `ValidationError`: `{ code: string, message: string, recoverable: boolean }`
- `ValidationWarning`: `{ code: string, message: string }`

#### `DependencyInfo` (L192–216)
- Required fields: `name`, `required`
- Optional fields: `version`, `installCommand`

#### `AdapterCommand` (L218–244)
- Required: `command: string`, `args: string[]`
- Optional: `env: Record<string, string>`

#### `AdapterConfig` (L246–285)
- Required: `sessionId`, `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath`, `launchConfig`
- Optional: `scriptArgs: string[]`
- `launchConfig` is typed as `GenericLaunchConfig` (index-access at L266)

#### `GenericLaunchConfig` (L287–313)
- All-optional: `stopOnEntry`, `justMyCode`, `env`, `cwd`, `args`

#### `LanguageSpecificLaunchConfig` (L315–329)
- Extends `GenericLaunchConfig` (tested via index access `config['pythonPath']`, `config['django']`, `config['pyramid']`), allowing arbitrary extra keys

#### `FeatureRequirement` (L332–366)
- Fields: `type: 'dependency' | 'version' | 'configuration'`, `description: string`, `required: boolean`

#### `AdapterCapabilities` (L368–455)
- Fully optional; supports ~34 boolean DAP capability flags
- Supports `exceptionBreakpointFilters: ExceptionBreakpointFilter[]`
- Supports `completionTriggerCharacters: string[]`
- Supports `supportedChecksumAlgorithms` (cast to `any` at L450 — likely enum type)

#### `ExceptionBreakpointFilter` (L457–483)
- Required: `filter: string`, `label: string`
- Optional: `description`, `default`, `supportsCondition`, `conditionDescription`

#### Error handling patterns (L486–513)
- Demonstrates creating environment, connection, and protocol errors with distinct codes
- Tests `recoverable` flag distinction between retryable vs. fatal errors

#### Type safety tests (L515–530)
- Confirms enum values are valid members of their respective enum via `Object.values()` containment

## Key Dependencies
- All types and classes imported from `@debugmcp/shared` (L6–22) — a workspace/monorepo shared package
- Test framework: `vitest` (`describe`, `it`, `expect`) (L5)

## Notable Patterns
- Type-level tests: TypeScript interfaces validated by constructing conforming object literals; TypeScript compiler enforces structural shape, runtime tests confirm property values
- `LanguageSpecificLaunchConfig` tested via bracket notation (L325–327) suggesting it is an index-signature type (`[key: string]: any`) extending `GenericLaunchConfig`
- `supportedChecksumAlgorithms` uses `as any` cast (L450), indicating the actual type uses a `ChecksumAlgorithm` enum from DAP protocol
- Count assertions (L36–39, L71–74, L101–104) act as regression guards against accidental enum member addition/removal in `@debugmcp/shared`