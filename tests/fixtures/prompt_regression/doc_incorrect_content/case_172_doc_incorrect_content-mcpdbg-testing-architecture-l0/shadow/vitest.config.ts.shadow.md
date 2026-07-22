# vitest.config.ts
@source-hash: 292dacfbe060c96b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## Vitest Configuration (`vitest.config.ts`)

### Purpose
Root Vitest configuration for a monorepo (`debugmcp`) that partitions tests into three projects: `unit` (parallel), `integration` (serial), and `e2e` (serial). Handles TypeScript path aliasing, ESM optimization, console filtering, and coverage reporting.

---

### Architecture: Three-Project Model (L239–288)
Selection is done via `--project <name>`, NOT `--exclude`, because `projects` silently ignores `--exclude` in Vitest 4.

| Project | Pool | Parallelism | Timeout | Include |
|---|---|---|---|---|
| `unit` | `forks` | `true` | 15s | All tests minus integration/e2e |
| `integration` | `forks` | `false` (1 worker) | 30s | `tests/**/integration/**` + `tests/stress/**` |
| `e2e` | `forks` | `false` (1 worker) | 30s | `tests/e2e/**` |

CI shortcut: `--project unit --project integration` == everything except e2e.

---

### Shared Resolver (`sharedResolve`, L8–30)
Injected into **every project** AND the root (required because projects don't inherit root `resolve` under `test.projects`):
- Extensions: `.ts`, `.js`, `.json`, `.node`
- Regex alias: `.js` imports → `.ts` (both relative and `src/`-prefixed)
- Named aliases for `@` (→ `./src`) and all `@debugmcp/*` workspace packages:
  - `@debugmcp/shared` → `packages/shared/src/index.ts`
  - `@debugmcp/adapter-mock` → `packages/adapter-mock/src/index.ts`
  - `@debugmcp/adapter-python`, `adapter-ruby`, `adapter-javascript`, `adapter-go`, `adapter-rust`, `adapter-java`, `adapter-dotnet` → respective `packages/*/src/index.ts`

### ESM Optimization (`sharedOptimizeDeps`, L33–35)
Pre-bundles `@modelcontextprotocol/sdk` and `@vscode/debugprotocol` for ESM compatibility.

---

### Console Filter (`onConsoleLog`, L42–101)
Three-tier filtering applied identically to both `unit` and `integration`/`e2e` projects:
1. **Whitelist** (return `true`): patterns like `FAIL`, `Error:`, `[Discovery Test]`, `[Workflow Test]`, `[Test Server]`, `[env-utils]`, `[process-listener-leak]`
2. **Noise filter** (return `false`): vite/webpack/HMR output, timestamps (`20` prefix), `[MCP Server]`, `[debug-mcp]`, `[ProxyManager`, `[SessionManager]`, log-level tags, `stdout |`, `stderr |`
3. **Test-file pass-through**: logs from `.test.` or `.spec.` files always shown
4. **Default**: show only `stderr`

---

### Coverage Configuration (L196–237, root-level only)
- Provider: `istanbul`
- Reporters: `text`, `json`, `html`, `json-summary`
- Output: `./coverage`
- `reportOnFailure: true`
- Include: `src/**/*.{ts,js}`, `packages/**/src/**/*.{ts,js}`
- Threshold: **80% statements**
- Notable coverage excludes:
  - Type-only files: `src/container/types.ts`, `src/dap-core/types.ts`
  - Separate-process files: `mock-adapter-process.ts`, `dap-proxy-entry.ts`
  - CLI/entry points: `packages/mcp-debugger/src/cli-entry.ts`, `batteries-included.ts`
  - Barrel exports: `packages/shared/src/index.ts`, `packages/shared/src/models/index.ts`
  - Error definitions: `src/errors/debug-errors.ts`

---

### Root-Level Test Options (L165–193)
- **Sequence**: `{ shuffle: { files: true, tests: false } }` — file-order shuffle only (within-file shuffle would break stateful integration/e2e suites sharing live debug sessions). Seed unpinned; reproduce with `--sequence.seed=<n>`.
- **Reporters**: `['dot', 'json']` on CI (detects worker death via JSON), `['default']` locally.
- **Output file**: `./test-results.json`

---

### Key Constants
- `UNIT_EXCLUDE` (L141): `sharedExclude` + `INTEGRATION_INCLUDE` + `E2E_INCLUDE` — ensures unit project doesn't double-run integration/e2e files
- `serialPool` (L153–159): `{ pool: 'forks', fileParallelism: false, maxWorkers: 1, isolate: true, testTimeout: 30000 }` — shared by `integration` and `e2e`
- `sharedSetupFiles` (L39): `['./tests/vitest.setup.ts']`

---

### Critical Invariants
- `sequence`, `reporters`, `outputFile`, and `coverage` MUST remain at root level — Vitest 4 silently ignores per-project versions of these.
- `sharedResolve` and `sharedOptimizeDeps` MUST be spread into every project config because projects don't inherit root Vite config.
- `UNIT_EXCLUDE` must always include all patterns in `INTEGRATION_INCLUDE` and `E2E_INCLUDE` to prevent test double-running.
