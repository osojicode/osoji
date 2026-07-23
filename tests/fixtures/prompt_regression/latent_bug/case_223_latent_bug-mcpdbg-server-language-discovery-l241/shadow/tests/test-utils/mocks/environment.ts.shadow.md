# tests\test-utils\mocks\environment.ts
@source-hash: ac99000281932f84
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:22Z

## Purpose
Provides a reusable, vitest-compatible mock for the `Environment` service used in tests. Centralizes default environment mock behavior to avoid repetition across test files.

## Interface: `EnvironmentMock` (L3–7)
Defines the contract for the mock object with three methods:
- `get(key: string): string | undefined` — lookup a single env var by key
- `getEnv(): Record<string, string>` — return the full env var map
- `isWindows(): boolean` — platform check

## Factory Function: `createEnvironmentMock` (L19–26)
Creates a `vi.fn()`-wrapped `EnvironmentMock` with sensible test defaults:
- `get` (L21): Returns `'false'` for `'MCP_CONTAINER'` (host mode default), falls back to `process.env[key]` for all other keys
- `getEnv` (L22): Returns `{}` (empty env map)
- `isWindows` (L23): Delegates to `process.platform === 'win32'` — reflects actual runtime platform

Accepts an optional `overrides?: Partial<EnvironmentMock>` (L19) that shallow-merges over the defaults via spread (L25), allowing per-test customization of individual methods without replacing the entire mock.

## Design Notes
- All methods are `vi.fn()` wrappers, so call counts and arguments are observable in tests.
- Overrides replace entire methods (not individual spy wrappers), so overridden functions lose `vi.fn()` tracking unless the caller wraps them explicitly.
- Intended companion to `src/utils/container-path-utils.ts` per the docstring.
- `MCP_CONTAINER` default of `'false'` enforces host-mode behavior by default across the test suite.