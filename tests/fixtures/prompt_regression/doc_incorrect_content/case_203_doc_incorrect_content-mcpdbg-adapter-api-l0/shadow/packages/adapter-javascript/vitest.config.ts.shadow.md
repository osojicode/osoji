# packages\adapter-javascript\vitest.config.ts
@source-hash: 6dc87debc6acf273
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:08Z

## Vitest Configuration — `packages/adapter-javascript`

Vitest configuration file for the `adapter-javascript` package. Configures test execution, coverage collection, and module resolution aliases for the JavaScript debug adapter.

### Test Settings (L5–18)
- **globals: true** (L6) — Vitest globals (`describe`, `it`, `expect`, etc.) injected without explicit imports
- **environment: 'node'** (L7) — Tests run in a Node.js environment
- **include** (L8): `tests/**/*.{test,spec}.ts` and `src/**/*.{test,spec}.ts`
- **exclude** (L9): `node_modules`, `dist`

### Coverage Configuration (L10–18)
- **provider: 'v8'** (L11) — Native V8 code coverage
- **reporters** (L12): `text` (console) and `lcov` (for CI/external tools)
- **reportsDirectory** (L13): `coverage/`
- **clean / cleanOnRerun: false** (L14–15) — Coverage artifacts are not wiped between runs
- **Excluded from coverage** (L16): `tests/**`, `vendor/**`, `dist/**`, `scripts/**`, `vitest.config.ts`, `src/types/**`, `src/javascript-adapter-factory.ts`, `src/javascript-debug-adapter.ts`, `coverage/**` — notably, two source entry-point files are explicitly excluded from coverage metrics
- **Thresholds** (L17): 90% minimum for lines, branches, functions, and statements

### Module Resolution / Aliases (L19–31)
Two alias scopes are defined (a quirk worth noting — aliases appear in both `test.alias` and `resolve.alias`):

1. **`test.alias`** (L19–24):
   - Regex `^(\\.{1,2}/.+)\\.js$` → `$1` (L21): Strips `.js` extensions from relative imports, enabling TypeScript ESM-style imports to resolve correctly in tests
   - `@debugmcp/shared` → `../shared/src/index.ts` (L23): Points the shared workspace package to its TypeScript source directly

2. **`resolve.alias`** (L26–31):
   - Extensions (L27): `.ts`, `.js`, `.json`, `.node`
   - `@debugmcp/shared` → `../shared/src/index.ts` (L29): Duplicate alias at the resolver level to ensure consistent resolution outside of test-specific contexts

### Key Architectural Notes
- The `.js` extension-stripping regex (L21) is essential for TypeScript projects using `"moduleResolution": "NodeNext"` or `"Bundler"` where imports must include `.js` extensions in source but resolve to `.ts` files at test time.
- `src/javascript-adapter-factory.ts` and `src/javascript-debug-adapter.ts` are excluded from coverage (L16), suggesting these are integration/entry-point files tested via other means or intentionally left out of unit coverage metrics.
- The `@debugmcp/shared` alias is duplicated across `test.alias` and `resolve.alias` (L23, L29) — both are needed for full resolution coverage in Vitest.