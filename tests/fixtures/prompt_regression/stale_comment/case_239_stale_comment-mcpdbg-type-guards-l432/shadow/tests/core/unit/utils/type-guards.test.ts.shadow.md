# tests\core\unit\utils\type-guards.test.ts
@source-hash: 6168cb6f31f4abb0
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:02Z

## Purpose
Unit test suite for `src/utils/type-guards.ts` — validates all exported type guard and validation utility functions for `AdapterCommand` and `ProxyInitPayload` at runtime boundaries (IPC, serialization, deserialization).

## Test Structure
Single top-level `describe('Type Guards', ...)` block (L20-677) with per-function sub-suites. Console spies (`consoleErrorSpy`, `consoleLogSpy`, `consoleWarnSpy`) are established in `beforeEach` (L25-29) and restored in `afterEach` (L31-33). The `logAdapterCommandValidation` suite uses fake timers fixed to `2024-01-01T12:00:00.000Z` (L587-588).

## Functions Under Test

### `isValidAdapterCommand` (L35-192)
- Accepts `unknown`, returns `boolean` (type predicate to `AdapterCommand`)
- Valid: object with non-empty string `command`, array `args` of strings, optional `env` as `Record<string,string>` (L36-62)
- TypeScript narrowing verified at L64-75
- Invalid: null/undefined, non-objects, arrays, missing/wrong-type `command`/`args`, non-string array elements in `args`, non-object or non-string-valued `env` (L77-138)
- Edge cases: symbol properties (L140-148), prototype-modified objects (L150-156), deeply nested env values fail (L158-176), large args (1000 items) must complete in <10ms (L178-191)

### `validateAdapterCommand` (L194-254)
- Throws `Error` with message `"Invalid adapter command from <source>"` for invalid input
- Calls `console.error('[TYPE VALIDATION ERROR]', ...)` on failure (L213-216)
- Returns input unchanged for valid commands (L201-203)
- Error includes `receivedType`, `receivedValue`, `requiredStructure` fields (L245-253)

### `hasValidAdapterCommand` (L256-303)
- Operates on `ProxyInitPayload` objects
- Returns `true` when `adapterCommand` is absent (L257-268) or valid (L271-286)
- Returns `false` when `adapterCommand` is present but invalid (e.g., empty command string) (L289-302)

### `validateProxyInitPayload` (L305-372)
- Requires 7 fields: `cmd`, `sessionId`, `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath` (L333-336)
- Throws `"Invalid ProxyInitPayload: must be an object"` for null/undefined/non-object (L321-329)
- Throws `"Invalid ProxyInitPayload: missing required field '<field>'"` for each missing field (L332-342)
- Throws `"Invalid ProxyInitPayload: adapterCommand validation failed"` and logs `console.error('[VALIDATION ERROR]', ...)` for invalid `adapterCommand` (L358-371)
- Returns input unchanged for valid payload (L316-318)

### `serializeAdapterCommand` (L374-436)
- Validates before serializing; throws via `validateAdapterCommand` with source `'serialization'` (L388-393)
- Produces JSON string with all fields preserved (L395-412)
- Throws on circular references (L414-423) and BigInt values (L425-435)

### `deserializeAdapterCommand` (L438-486)
- Throws `"Failed to parse adapter command from <source>"` for invalid JSON (L450-453)
- Validates parsed result; throws `"Invalid adapter command from deserialization-<source>"` for invalid structure (L455-459, L467-471)
- Round-trips correctly with `serializeAdapterCommand` (L474-485)

### `createAdapterCommand` (L488-541)
- Minimal call: `createAdapterCommand('python')` → `{ command: 'python', args: [], env: {} }` (L489-497)
- Throws `'Invalid command for adapter: "<value>"'` for empty string, null, or non-string (L519-526)
- `undefined` args parameter defaults to `[]` (L528-530)
- Created command passes `isValidAdapterCommand` (L533-540)

### `getAdapterCommandProperty` (L543-581)
- Returns property value from valid `AdapterCommand` (L550-553)
- Returns `defaultValue` and logs `console.warn('[TYPE GUARD] Invalid adapter command, returning default for <prop>')` for invalid input (L556-562)
- Returns default for undefined optional property (e.g., `env` when absent) (L565-573)
- Handles null/undefined inputs gracefully (L575-580)

### `logAdapterCommandValidation` (L583-676)
- Valid: logs via `console.log('[ADAPTER COMMAND VALIDATION]', JSON.stringify({...}, null, 2))` (L594-610)
- Invalid: logs via `console.error('[ADAPTER COMMAND VALIDATION ERROR]', JSON.stringify({...}, null, 2))` (L613-631)
- Logged object shape: `{ source, isValid, command, timestamp, details? }` (L663-668)
- Timestamp from `new Date().toISOString()` (L633-640)
- Output is 2-space indented JSON (L642-651)

## Key Dependencies
- `../../../../src/utils/type-guards.js` — SUT (all 8 functions imported at L7-16)
- `@debugmcp/shared` — `AdapterCommand` type (L17)
- `../../../../src/proxy/dap-proxy-interfaces.js` — `ProxyInitPayload` type (L18)
- `vitest` — test framework (L5)

## Notable Patterns
- Console method spying used to assert logging behavior without cluttering test output
- Fake timers used in `logAdapterCommandValidation` suite for deterministic timestamp assertions
- `ProxyInitPayload` used as concrete type for `hasValidAdapterCommand` tests — requires 7 fields including `cmd: 'init'`
- `BigInt` env value test (L425-435) documents that validation occurs after JSON.stringify, so the TypeError from JSON.stringify is the expected error, not a validation error
- Deserialization error source is prefixed: `"deserialization-<source>"` not just `"<source>"`
