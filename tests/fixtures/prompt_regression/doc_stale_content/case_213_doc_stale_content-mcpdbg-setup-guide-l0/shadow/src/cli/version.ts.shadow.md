# src\cli\version.ts
@source-hash: 1f32b97ce06b2a8e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:59Z

## `src/cli/version.ts`

Resolves and returns the current package version by searching for `package.json` at multiple candidate paths relative to the module directory or CWD. Falls back to `'0.0.0'` if no valid version string is found.

### Key Symbols

- **`FALLBACK_VERSION`** (L5): Constant `'0.0.0'` returned when no `package.json` with a valid `version` field is found.
- **`getModuleDirectory()`** (L7–18): Internal helper that resolves the current module's directory in a cross-runtime compatible way. Priority: `__dirname` (CJS) → `import.meta.url` (ESM) → `process.cwd()` (fallback). Returns a `string` directory path.
- **`getVersion()`** (L20–43): Public export. Iterates over three candidate `package.json` paths in order:
  1. `<moduleDir>/../../package.json`
  2. `<moduleDir>/../package.json`
  3. `<cwd>/package.json`

  Reads the first file whose `.version` is a non-empty string and returns it. Errors are swallowed silently when `process.env.CONSOLE_OUTPUT_SILENCED === '1'`; otherwise they are logged to `console.error`. Returns `FALLBACK_VERSION` if all candidates fail.

### Patterns & Design Decisions

- **CJS/ESM dual compatibility**: `getModuleDirectory()` handles both `__dirname` (CommonJS) and `import.meta.url` (ESM) environments, with `process.cwd()` as a last resort.
- **Ordered candidate resolution**: Paths are tried in order from most-specific (deep dist output) to least-specific (project root), allowing the function to work correctly whether the compiled output is one or two levels deep inside the package root.
- **Stdio-safe logging**: Error output is suppressed when `CONSOLE_OUTPUT_SILENCED=1` (L36), preventing noise in MCP stdio transport mode.
- **Defensive version validation** (L31): Guards against `package.json` files that exist but have a missing or empty `version` field before returning.

### Dependencies

- `fs` (Node stdlib): `readFileSync` for synchronous `package.json` reading.
- `path` (Node stdlib): `resolve`, `dirname` for path construction.
- `url` (Node stdlib): `fileURLToPath` for ESM `import.meta.url` → file path conversion.
