# tests\core\unit\utils\type-guards.test.ts
@source-hash: 6168cb6f31f4abb0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:14Z

## Purpose
Unit test suite for the `src/utils/type-guards.ts` module, covering runtime type safety utilities for `AdapterCommand` and `ProxyInitPayload` at IPC/serialization boundaries.

## Test Structure

### Top-level describe: `Type Guards` (L20–676)
- **Setup (L25–33):** Spies on `console.error`, `console.log`, and `console.warn` before each test; restores all mocks after each test.

### `isValidAdapterCommand` (L35–192)
Type guard predicate for `AdapterCommand` shape. Tests verify:
- Returns `true` for valid commands (with/without `env`, with empty `args`) (L36–62)
- TypeScript type narrowing behavior (L64–75)
- Returns `false` for `null`, `undefined`, non-objects, arrays, symbols (L77–91)
- Returns `false` for missing/invalid `command` (non-string, empty string) (L93–101)
- Returns `false` for missing/non-array `args` or `args` containing non-strings (L103–118)
- Returns `false` for invalid `env` field (non-object, null, array, or values that aren't strings) (L120–138)
- Handles symbol properties and modified prototypes gracefully (L140–156)
- Handles deeply nested `env` objects (100 levels; returns false due to non-string leaf values) (L158–176)
- Performance: 1000-element `args` array validates in <10ms (L178–191)

### `validateAdapterCommand` (L194–254)
Throwing validator that returns valid command or throws with structured error. Tests verify:
- Returns valid command unchanged without logging (L195–204)
- Throws `'Invalid adapter command from {source}'` and calls `console.error('[TYPE VALIDATION ERROR]', ...)` for invalid input (L206–217)
- Source string is embedded in error message (including empty and very long strings) (L219–236)
- Error object includes `receivedType`, `receivedValue`, `requiredStructure` fields (L245–253)

### `hasValidAdapterCommand` (L256–303)
Checks if a `ProxyInitPayload`'s optional `adapterCommand` field is valid (or absent). Tests verify:
- Returns `true` when `adapterCommand` is absent (L257–269)
- Returns `true` for valid `adapterCommand` (L271–287)
- Returns `false` for invalid `adapterCommand` (e.g., empty command string) (L289–302)

### `validateProxyInitPayload` (L305–372)
Validates full `ProxyInitPayload` objects. Uses a shared `validPayload` fixture (L306–314). Tests verify:
- Returns valid payload unchanged (L316–319)
- Throws `'Invalid ProxyInitPayload: must be an object'` for non-objects (L321–330)
- Throws `"Invalid ProxyInitPayload: missing required field '{field}'"` for each of 7 required fields (L332–343): `cmd`, `sessionId`, `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath`
- Validates optional `adapterCommand` when present; throws `'Invalid ProxyInitPayload: adapterCommand validation failed'` and calls `console.error('[VALIDATION ERROR]', ...)` for invalid (L345–371)

### `serializeAdapterCommand` (L374–436)
Serializes `AdapterCommand` to JSON string with pre-validation. Tests verify:
- Produces parseable JSON matching original (L375–386)
- Validates before serializing (throws `'Invalid adapter command from serialization'` for invalid input) (L388–393)
- Preserves all fields (L395–412)
- Circular references throw (JSON.stringify TypeError) (L414–423)
- BigInt values throw `'Do not know how to serialize a BigInt'` — notably, BigInt in `env` bypasses `isValidAdapterCommand` validation (L425–435)

### `deserializeAdapterCommand` (L438–486)
Parses JSON string to validated `AdapterCommand`. Tests verify:
- Parses valid JSON and validates result (L439–448)
- Throws `'Failed to parse adapter command from {source}'` for invalid JSON syntax (L450–453)
- Throws `'Invalid adapter command from deserialization-{source}'` for valid JSON with invalid structure (L455–459, L467–472)
- Round-trip serialize/deserialize correctness (L474–485)

### `createAdapterCommand` (L488–541)
Factory function building validated `AdapterCommand`. Tests verify:
- Minimal call: `createAdapterCommand('python')` → `{ command: 'python', args: [], env: {} }` (L489–497)
- With explicit `args` and `env` (L499–517)
- Throws `'Invalid command for adapter: "{cmd}"'` for empty string, null, numbers (L519–526)
- `undefined` args defaults to `[]` (L528–531)
- Created command passes `isValidAdapterCommand` (L533–540)

### `getAdapterCommandProperty` (L543–581)
Safe property accessor with fallback. Tests verify:
- Returns actual property values for valid commands (L550–553)
- Returns default and calls `console.warn('[TYPE GUARD] Invalid adapter command, returning default for command')` for invalid (L556–563)
- Returns default for undefined optional property (`env`) (L565–573)
- Handles `null`/`undefined` inputs; `console.warn` called twice (L575–580)

### `logAdapterCommandValidation` (L583–676)
Structured diagnostic logger. Uses fake timers pinned to `2024-01-01T12:00:00.000Z` (L586–588). Tests verify:
- Valid commands logged via `console.log` with prefix `'[ADAPTER COMMAND VALIDATION]'` and JSON containing `"source"`, `"isValid": true` (L594–611)
- Invalid commands logged via `console.error` with prefix `'[ADAPTER COMMAND VALIDATION ERROR]'`, `"isValid": false`, and optional `"details"` (L613–631)
- Timestamp `"2024-01-01T12:00:00.000Z"` included in output (L633–640)
- Output is 2-space indented JSON (`{\n  "source"`) (L642–651)
- Complex `details` objects (nested arrays/objects) are serialized into the structured log entry (L653–675)

## Key Dependencies
- **Tested module:** `../../../../src/utils/type-guards.js` (L16)
- **Types:** `AdapterCommand` from `@debugmcp/shared` (L17); `ProxyInitPayload` from `../../../../src/proxy/dap-proxy-interfaces.js` (L18)
- **Test framework:** `vitest` (L5)

## Notable Patterns
- **BigInt edge case (L425–435):** The test comment notes BigInt in `env` throws before validation can run. This implies `isValidAdapterCommand` may not catch BigInt values in `env` — validation only checks string values, so a BigInt would fail the string check. However the test expects the serialization throw to come from `JSON.stringify`, suggesting validation order may allow BigInt through the type guard or BigInt values specifically bypass env validation.
- **Source prefix in deserialization errors (L455–472):** Error prefix is `deserialization-{source}`, not just `{source}` — important contract for error message consumers.
- **`hasValidAdapterCommand` with absent field (L257–269):** Returns `true` when `adapterCommand` is undefined, treating absence as valid.
