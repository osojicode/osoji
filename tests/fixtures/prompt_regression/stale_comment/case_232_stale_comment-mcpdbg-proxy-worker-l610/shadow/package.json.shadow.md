# package.json
@source-hash: 11d15dfe044190e8
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:41Z

## Monorepo Root Package Configuration

This is the root `package.json` for the `mcp-debugger` pnpm monorepo (v0.23.0). It is **private** and not published to npm. It orchestrates the entire workspace, defining shared scripts, dependencies for the server core, and workspace topology.

### Workspace Layout (L11–18)
- All packages live under `packages/*`
- `nohoist` for `**/debugpy` and `**/node-inspector` — these are kept in their respective package `node_modules` rather than hoisted to root, likely because they are native/binary tools with path-sensitive behavior.

### Key Scripts (L20–116)

**Build pipeline:**
- `prebuild` (L28): Cleans src artifacts, removes `dist/`, then vendors adapters
- `build` (L29): Runs `build:packages`, TypeScript project-reference build (`tsc -b -f .`), `postbuild`, and `bundle`
- `build:packages` (L34): Delegates to `scripts/build-packages.cjs` (custom build orchestrator)
- `postbuild` (L103): Runs `scripts/copy-proxy-files.cjs`
- `bundle` (L102): Delegates to `@debugmcp/mcp-debugger` package build
- `build:shared` (L30): Builds `@debugmcp/shared` package
- `build:adapters` (L31): Builds mock, python, ruby adapters (excludes JS)
- `build:adapters:all` (L32): Builds all four adapters including JS
- `build:ci` (L36): CI-specific build without bundling step

**Vendor/adapter management:**
- `vendor:adapters` (L24): Runs `build:adapter` script recursively in all packages
- `postinstall` (L22): Auto-runs vendor adapters after `pnpm install`
- `vendor:force` (L25): Clean + rebuild all adapter vendors
- `vendor:status` (L26): Checks adapter state via `scripts/check-adapters.js`

**Test suite (L44–116):**
- `test` (L44): Full pipeline — build + docker check + vitest run (all projects)
- `test:unit` (L48): Vitest `unit` project only
- `test:integration` (L54): Vitest `integration` project only
- `test:e2e` (L56): Docker pre-check + Vitest `e2e` project
- `test:strict` (L50): Unit + integration with `LEAK_GUARD_STRICT=1` env
- `test:ci` (L61): Alias for `test:no-docker`
- `test:ci-coverage` (L63): Build + vitest coverage for unit + integration
- `test:coverage` (L77): Full coverage run; `posttest:coverage` calls `analyze-coverage.js`
- `test:stress` (L75): Integration stress tests with `RUN_STRESS_TESTS=true`
- `test:flake` (L52): Flake hunt via `scripts/flake-hunt.mjs`
- All test variants have `posttest:*` hooks running `scripts/cleanup-test-processes.js`

**Validation and release:**
- `validate` (L112), `validate:quick` (L113), `validate:smoke` (L114): Push validation scripts
- `release:dry-run` (L116): Bash-based release dry run

**Local CI simulation (act):**
- `act:*` scripts (L105–111): Use `scripts\act-runner.cmd` (Windows-style paths) to run GitHub Actions locally

### Entry Points (L137–141)
- `main`: `dist/index.js`
- `type`: `module` (ESM)
- `bin.mcp-debugger`: `./dist/index.js` — CLI entry point

### Runtime Dependencies (L142–156)
Core server dependencies:
- `@modelcontextprotocol/sdk ^1.29.0` — MCP protocol implementation
- `@vscode/debugprotocol ^1.68.0` — DAP (Debug Adapter Protocol) types
- `commander ^15.0.0` — CLI argument parsing
- `express ^5.2.1` — HTTP server (proxy/API)
- `winston ^3.19.0` — Logging
- `uuid ^14.0.1` — ID generation
- `lru-cache ^11.1.5` — Caching
- `fs-extra ^11.3.6` — File system utilities
- `eventsource ^4.1.0` — SSE client
- `debug ^4.4.3` — Debug logging
- `which ^7.0.0` — Executable resolution
- `@debugmcp/shared workspace:*` — Internal shared package

### Optional Dependencies (L157–166)
Language adapter packages, all at `workspace:*`:
- `@debugmcp/adapter-dotnet`, `adapter-go`, `adapter-java`, `adapter-javascript`, `adapter-mock`, `adapter-python`, `adapter-ruby`, `adapter-rust`

### Dev Dependencies (L167–189)
- `vitest ^4.1.10` — Test runner (with `@vitest/coverage-istanbul` and `@vitest/coverage-v8`)
- `typescript ^6.0.2` — TypeScript compiler
- `eslint ^10.7.0` + `typescript-eslint ^8.64.0` — Linting
- `esbuild ^0.28.1` — Bundler
- `tsup ^8.5.1` — Build tool
- `husky ^9.1.7` — Git hooks (`prepare` runs husky)
- `cross-env ^10.1.0` — Cross-platform env var setting
- `fast-check ^4.9.0` — Property-based testing
- `rimraf ^6.1.3` — Cross-platform rm -rf

### pnpm Configuration (L190–204)
- `onlyBuiltDependencies: [esbuild]` — Only esbuild runs install scripts
- `overrides`: Security/compatibility pins for `vite` (7.3.6), `path-to-regexp` (≥8.4.0), `brace-expansion` (≥5.0.6), `hono` (^4.12.25), `fast-uri` (^3.1.2), `qs` (^6.15.2), `ip-address` (^10.1.1), `esbuild` (^0.28.1)

### Node Requirement (L134–136)
- `engines.node: >=22.0.0` — Requires Node.js 22+

### Architectural Notes
- This is a **pnpm workspace monorepo** with a server core at the root + language adapters as separate packages
- The build system uses TypeScript project references (`tsc -b`) for incremental compilation
- Adapters are treated as optional/vendored — they may not all be present, controlled by `build:adapter` hooks
- The `act:*` scripts use Windows cmd-style paths (backslashes), suggesting primary dev environment is Windows but CI runs Linux
- Docker integration is used for E2E tests (`pretest:docker` step)