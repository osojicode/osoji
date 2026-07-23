# tests\unit\implementations\process-manager-impl.test.ts
@source-hash: 043b86c81e3340b2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:07Z

## Purpose
Unit test suite for `ProcessManagerImpl`, covering `spawn` delegation to `child_process.spawn` and `exec` return-type edge-case handling via a custom `util.promisify` mock.

## Module-Level Mocking Strategy (L9–29)
Two modules are hoisted-mocked at the top:

- **`child_process`** (L9–12): `spawn` and `exec` replaced with `vi.fn()`. Tests control `spawn` via `(spawn as any).mockReturnValue(...)`.
- **`util`** (L14–29): `promisify` replaced with a factory that returns an async function reading `globalThis.__promisifyBehavior` and `globalThis.__promisifyResult` at call time. This pattern works around the hoisting constraint (vi.mock cannot close over external `let` variables). When `__promisifyBehavior === 'reject'`, throws `__promisifyResult`; otherwise resolves with it. Default: `behavior='resolve'`, `result=null`.

## Test Fixture Setup (L39–54)
- `beforeEach`: clears all mocks, creates a fresh `ProcessManagerImpl`, spies on `console.warn`, resets globals to `{ behavior: 'resolve', result: null }`.
- `afterEach`: restores `console.warn`, deletes both `globalThis` control properties.

## `spawn` Tests (L56–99)
| Test | Key assertion |
|------|--------------|
| Command + args + options (L57–71) | `spawn` called with exact args/options; return value passed through |
| Without options (L73–81) | `spawn` called with `{}` as third arg (confirms default options) |
| Spawn error propagation (L83–87) | `spawn` throwing propagates through `processManager.spawn` |
| Default empty args (L89–98) | Calling `processManager.spawn('pwd')` uses `[]` as default args |

## `exec` Tests (L101–198)
All tests exercise the resolved/rejected shape that `ProcessManagerImpl.exec` expects from the promisified exec wrapper.

| Test | `__promisifyResult` | Expected outcome |
|------|---------------------|-----------------|
| Object with stdout/stderr (L102–115) | `{ stdout, stderr }` | Resolves to that object |
| Array return (L117–124) | `['...', '...']` | Rejects: "unexpected type: object" |
| String return (L126–133) | `'string output'` | Rejects: "unexpected type: string" |
| Number return (L135–142) | `42` | Rejects: "unexpected type: number" |
| Null return (L144–151) | `null` | Rejects: "unexpected type: object" |
| Object without stdout/stderr (L153–160) | `{ foo, baz }` | Rejects: "unexpected type: object" |
| Empty array (L162–169) | `[]` | Rejects: "unexpected type: object" |
| Exec error (L171–177) | `Error('Command failed')` (rejected) | Rejects with that error |
| Exec error with code (L179–198) | `Error` with `.code=127`, `.stdout`, `.stderr` (rejected) | Rejects; error object preserves all properties |

## Key Architectural Observations
- **`globalThis` control variables** are the only way to communicate with the hoisted `util.promisify` mock; standard closure capture fails due to hoisting.
- The comment labels on several `exec` tests ("dead branch removed") signal tests validating that previously-handled return shapes (array, plain string) now go to the error branch in the implementation, confirming a refactor of `ProcessManagerImpl.exec`.
- `console.warn` is spied but never asserted in any test — possibly a precautionary suppression for implementation-side warnings.
- The error message format `'[ProcessManagerImpl] execAsync resolved to unexpected type: <typeof result>'` (L122, 130, 139, 149, 158, 167) acts as a cross-file contract with `ProcessManagerImpl.exec`'s error branch.

## Dependencies
- `vitest` — test runner + assertion library
- `child_process` (mocked) — `spawn`, `exec`
- `util` (mocked) — `promisify`
- `ProcessManagerImpl` from `src/implementations/process-manager-impl.js`