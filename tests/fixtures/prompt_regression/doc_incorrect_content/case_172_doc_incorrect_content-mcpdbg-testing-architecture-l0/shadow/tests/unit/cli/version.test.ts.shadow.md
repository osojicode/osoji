# tests\unit\cli\version.test.ts
@source-hash: 5e0888fd3d74fa77
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:44Z

## Unit Tests: `getVersion` (CLI Version Utility)

Tests for `src/cli/version.js`'s `getVersion` function, covering package.json reading, fallback behavior, error handling, and console suppression.

### Test Structure

- **Suite:** `"Version Utility"` (L7–85), using Vitest
- **Subject under test:** `getVersion` imported from `../../../src/cli/version.js` (L3)
- **Mocked module:** `fs` (entire module mocked via `vi.mock('fs')` at L5)
- **Setup/teardown:** `consoleErrorSpy` on `console.error` created in `beforeEach` (L10–12), restored and all mocks reset in `afterEach` (L14–17)

### Test Cases

| Test | Lines | Description |
|------|-------|-------------|
| Happy path | L19–31 | Mocks `fs.readFileSync` to return valid JSON with `version: '1.2.3'`; asserts `getVersion()` returns `'1.2.3'` and that `readFileSync` was called with a path containing `'package.json'` and encoding `'utf8'` |
| Missing version field | L33–44 | JSON has no `version` key; expects fallback `'0.0.0'` |
| File read failure | L46–56 | `readFileSync` throws `Error('File not found')`; expects `'0.0.0'` and `console.error` called with `'Failed to read version from package.json:'` + the error object |
| Invalid JSON | L58–65 | `readFileSync` returns `'{ invalid json }'`; expects `'0.0.0'` and `console.error` called with message + any Error |
| Empty JSON object | L67–73 | `readFileSync` returns `'{}'`; expects `'0.0.0'` |
| Console suppression | L75–84 | `CONSOLE_OUTPUT_SILENCED=1` env var stubbed via `vi.stubEnv`; `readFileSync` throws; asserts `console.error` is **not** called |

### Key Behavioral Contracts Verified

1. `getVersion()` reads `package.json` using `fs.readFileSync` with `'utf8'` encoding
2. Returns `'0.0.0'` as the universal fallback for: missing `version` field, empty object, read errors, or parse errors
3. Error logging via `console.error` uses the message `'Failed to read version from package.json:'` followed by the caught error
4. The `CONSOLE_OUTPUT_SILENCED` environment variable (value `'1'`) suppresses error logging in `getVersion`

### Dependencies

- `vitest`: `describe`, `it`, `expect`, `vi`, `beforeEach`, `afterEach`
- `fs`: mocked entirely; only `fs.readFileSync` is exercised
- `src/cli/version.js`: exports `getVersion` — the sole function under test