# src\utils\type-guards.ts
@source-hash: a29f3dfcd372f6c5
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:11Z

## Purpose
Runtime type-guard and validation utilities for `AdapterCommand` and `ProxyInitPayload` structures, used at IPC/serialization boundaries to enforce type safety before data crosses process boundaries.

## Key Exports

### `isValidAdapterCommand` (L13–49)
Type predicate (`obj is AdapterCommand`). Validates:
- `command`: non-empty string (required)
- `args`: array of strings (required)
- `env`: optional `Record<string, string>` — must not be array, must have all string keys and values

### `validateAdapterCommand` (L55–74)
Throws detailed `Error` with received type, value, source, and required structure if `isValidAdapterCommand` fails. Returns typed `AdapterCommand` on success. Logs to `console.error` on failure.

### `hasValidAdapterCommand` (L80–86)
Checks the optional `adapterCommand` field on a `ProxyInitPayload`. Returns `true` if field is absent (falsy) or passes `isValidAdapterCommand`.

### `validateProxyInitPayload` (L92–131)
Validates `unknown` → `ProxyInitPayload`. Checks:
- Must be object
- Required fields: `cmd`, `sessionId`, `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath` (none may be `undefined`/`null`)
- `sessionId`: must be string
- `adapterPort`: must be number
- `adapterCommand`: validated via `isValidAdapterCommand` if present
- `launchConfig`: must be object if present

### `serializeAdapterCommand` (L137–140)
Validates then `JSON.stringify`s an `AdapterCommand`. Guards against serializing invalid state.

### `deserializeAdapterCommand` (L146–156)
Parses a JSON string and validates the result as `AdapterCommand`. Source label appended with `deserialization-` prefix for error tracing.

### `createAdapterCommand` (L162–179)
Factory that constructs `AdapterCommand` with defaults (`args = []`, `env = {}`), validates command string is non-empty, then runs `validateAdapterCommand` before returning.

### `getAdapterCommandProperty` (L185–196)
Generic safe property accessor. Returns `defaultValue` with a `console.warn` if `cmd` is not a valid `AdapterCommand`, otherwise returns `cmd[property] ?? defaultValue`.

### `logAdapterCommandValidation` (L202–220)
Structured logging helper. Logs ISO-timestamped JSON to `console.log` (valid) or `console.error` (invalid). Pure side-effect utility.

## Dependencies
- `AdapterCommand` from `@debugmcp/shared` — the core command shape being validated
- `ProxyInitPayload` from `../proxy/dap-proxy-interfaces.js` — the IPC init payload shape

## Patterns
- All validators follow a consistent "throw with details" pattern for hard failures
- Soft validation (type predicates) vs. hard validation (throwing wrappers) are kept separate
- `validateAdapterCommand` is reused internally by `serializeAdapterCommand`, `deserializeAdapterCommand`, and `createAdapterCommand` to ensure a single validation path
- `env` defaults to `{}` in `createAdapterCommand` (L174), meaning the created object always has `env` defined even though `isValidAdapterCommand` treats it as optional

## Constraints / Invariants
- `isValidAdapterCommand`: `env` keys are always strings (guaranteed by `Object.entries`), so only the value check at L42 is functionally meaningful
- `validateProxyInitPayload` does not type-check most required fields beyond `sessionId` and `adapterPort`; other required fields only check for `undefined`/`null`