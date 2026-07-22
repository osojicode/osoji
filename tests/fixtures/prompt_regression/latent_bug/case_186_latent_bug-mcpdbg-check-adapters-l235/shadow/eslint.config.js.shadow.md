# eslint.config.js
@source-hash: 00ec3a757ef396c7
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:02Z

## ESLint Flat Config (`eslint.config.js`)

ESLint configuration using the flat config format (ESLint v9+). Exports a single default array of config objects applied in order.

### Config Segments (in priority order)

1. **Global ignores (L7–30):** Excludes build artifacts (`build/`, `**/*.d.ts`, `coverage/`), `node_modules/`, `sessions/`, log files, experimental scripts (`scripts/experiments/**`), manual test files (`tests/manual/**`, `tests/jest-register.js`, `test-*.js`, `test-*.cjs`), test helper CJS/JS files, and `tests/mcp_debug_test.js`.

2. **TypeScript recommended spread (L33):** Applies `tseslint.configs.recommended` across all TS files (scoped internally by typescript-eslint).

3. **TypeScript unused-vars override (L36–48):** Scoped to `**/*.ts`. Sets `@typescript-eslint/no-unused-vars` to `"error"` with ignore patterns for underscore-prefixed args, vars, and caught errors (`^_`).

4. **JavaScript files config (L51–61):** Scoped to `**/*.{js,mjs,cjs}`. Spreads `js.configs.recommended`, sets Node.js globals, `ecmaVersion: "latest"`, `sourceType: "module"`.

5. **Node globals for TS sources (L64–72):** Scoped to `src/**/*.ts`, `packages/*/src/**/*.ts`, `tests/**/*.ts`. Injects `globals.node` into language options.

6. **Test file leniency (L75–84):** Scoped to `tests/**/*.ts`. Downgrades `no-explicit-any`, `no-unused-vars`, `ban-ts-comment` to warnings; enforces `no-floating-promises` as error to prevent silent async failures.

7. **Mock file leniency (L87–94):** Scoped to `tests/test-utils/mocks/**/*.ts`. Turns off `no-explicit-any`, `no-unsafe-function-type`, `ban-ts-comment` entirely for maximum flexibility in mock definitions.

8. **Script utilities leniency (L96–106):** Scoped to `scripts/**/*.{js,mjs,cjs}`. Disables `no-unused-vars`, `no-useless-escape`, `no-useless-assignment`, `@typescript-eslint/no-unused-vars`, and `@typescript-eslint/no-require-imports` to reduce noise in maintenance/utility scripts.

### Key Architectural Decisions
- Uses **flat config** format (array export), not legacy `.eslintrc`.
- Rule strictness is graduated: source TS > test TS > mock TS; script JS is most relaxed.
- Underscore-prefix convention for intentionally unused variables is enforced project-wide for TS.
- `no-floating-promises` is elevated to error in tests despite general test leniency — explicitly guards against silent async failures.
- Mock files get the most permissive ruleset to allow flexible test double patterns.
