# tests\adapters\javascript\integration\javascript-session-smoke.test.ts
@source-hash: e4354114cdb6d289
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:59Z

## JavaScript Adapter Session Smoke Integration Test

Single integration test suite (`L11–L82`) verifying the JavaScript debug adapter's session lifecycle: adapter registry setup, launch config transformation, and adapter command construction — without full module mocking.

### Purpose
Smoke-tests the `JavascriptAdapterFactory` end-to-end through the `AdapterRegistry` to confirm:
1. A TypeScript program launch config is correctly transformed (preserving `runtimeExecutable: 'tsx'` and empty `runtimeArgs`).
2. `buildAdapterCommand` returns an absolute Node executable path and an args array whose first element resolves to the vendored `vsDebugServer.cjs` entry point.

### Key Elements

#### `norm` helper (L7–L9)
Normalises a path-like unknown value to a forward-slash string. Used to make Windows backslash paths comparable against POSIX-style suffix assertions (e.g., `/vendor/js-debug/vsDebugServer.cjs`).

#### Test Suite Constants (L12–L17)
- `isWin` — runtime Windows detection for cross-platform dummy paths.
- `sessionId = 'session-js-3'` — stable session identifier passed into adapter config.
- `dummyScriptTs` — platform-appropriate absolute path to a `.ts` file (`C:\\proj\\app.ts` / `/proj/app.ts`).
- `logDir` — `<cwd>/logs/tests`, derived at test load time.
- `adapterHost = '127.0.0.1'`, `adapterPort = 56789` — fixed DAP listen coordinates.

#### `beforeEach` / `afterEach` (L21–L35)
- Saves and restores `process.env.NODE_OPTIONS` to prevent cross-test pollution.
- Calls `resetAdapterRegistry()` before and after each test to ensure a clean registry state.
- Calls `vi.clearAllMocks()` / `vi.restoreAllMocks()` for vitest mock hygiene.

#### Integration Test: `'provides js-debug launch config…'` (L37–L82)
1. **Arrange**: Creates a fresh registry (`validateOnRegister: false`) and registers `JavascriptAdapterFactory` under the key `'javascript'` (L39–40).
2. **Create adapter**: `registry.create('javascript', adapterConfig)` with an `as any` cast to bypass strict typing (L53).
3. **`transformLaunchConfig`** (L56–71): Passes a config with `program: dummyScriptTs`, `runtimeExecutable: 'tsx'`, `runtimeArgs: []`. Asserts the returned config preserves `runtimeExecutable === 'tsx'` and `runtimeArgs` is either an empty array or `undefined`.
4. **`buildAdapterCommand`** (L74–81): Asserts:
   - `cmd.command` is a non-empty absolute path string (the Node.js executable).
   - `cmd.args[0]` (normalised) ends with `/vendor/js-debug/vsDebugServer.cjs`.
   - `cmd.args[1]` equals the string `'56789'` (port as string).

### Dependencies
- **`getAdapterRegistry` / `resetAdapterRegistry`** from `../../../../src/adapters/adapter-registry.js` — central registry management.
- **`JavascriptAdapterFactory`** from `../../../../packages/adapter-javascript/src/index.js` — the SUT (system under test).
- **`vitest`** — test runner with `describe`, `it`, `expect`, `beforeEach`, `afterEach`, `vi`.
- **`path`** (Node stdlib) — for `path.join`, `path.isAbsolute`.

### Architectural Notes
- Uses `as any` casts deliberately to avoid strict adapter config typing, enabling a lean integration test without full type scaffolding.
- Cross-platform path handling is centralised in the `norm` helper rather than branching per assertion.
- `validateOnRegister: false` bypasses any config schema validation at registry registration time, keeping the smoke test focused on runtime behaviour.
- The test explicitly sets `runtimeExecutable: 'tsx'` to produce a deterministic result without module mocking — this avoids filesystem probing for tsx/ts-node resolution.