# package.json
@source-hash: 11d15dfe044190e8
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:56Z

## Monorepo Root `package.json`

**Package:** `mcp-debugger-monorepo` (private, v0.23.0) — root workspace configuration for the MCP Debugger project, which provides run-time step-through debugging for LLM agents via the Model Context Protocol (MCP) and Debug Adapter Protocol (DAP).

---

### Workspace Configuration (L11–19)
- Manages all packages under `packages/*`
- `nohoist` entries for `**/debugpy` and `**/node-inspector` — these native/external debug tools must not be hoisted to root `node_modules`

---

### Entry Points (L137–141)
- **main:** `dist/index.js`
- **bin:** `mcp-debugger` → `./dist/index.js`
- **type:** `module` (ESM)
- **engines:** Node.js `>=22.0.0`

---

### Key Script Groups

**Build pipeline (L28–39):**
- `prebuild` (L28): cleans src artifacts, removes `dist/`, triggers vendor adapters
- `build` (L29): runs `build:packages`, TypeScript project build (`tsc -b -f .`), `postbuild`, and `bundle`
- `build:packages` (L34): delegates to `scripts/build-packages.cjs`
- `build:packages:ci` (L35): same with `BUILD_SCRIPT=build:ci` env override
- `build:ci` (L36): CI-specific build without bundling
- `postbuild` (L103): runs `scripts/copy-proxy-files.cjs`
- `bundle` (L102): invokes `@debugmcp/mcp-debugger` package build via pnpm filter
- `build:shared` (L30): builds `@debugmcp/shared` only
- `build:adapters` (L31): builds mock, Python, and Ruby adapters
- `build:adapters:all` (L32): same + JavaScript adapter

**Vendor management (L22–27):**
- `vendor:adapters` (L24): recursively runs `build:adapter` in all packages (if present)
- `postinstall` (L22): auto-runs `vendor:adapters` after install
- `vendor:force` (L25): clean + rebuild vendors
- `vendor:status` (L26): `scripts/check-adapters.js`

**Test suite (L44–95):**
- `test` (L44): full build + docker check + vitest run
- `test:unit` (L48): vitest `unit` project only
- `test:integration` (L54): vitest `integration` project only
- `test:e2e` (L56): requires docker build check + `e2e` vitest project
- `test:strict` (L50): `LEAK_GUARD_STRICT=1` for unit + integration projects
- `test:flake` (L52): `scripts/flake-hunt.mjs` for flakiness detection
- `test:ci` (L61): alias for `test:no-docker`
- `test:ci-coverage` (L63): build + vitest coverage on unit + integration
- `test:stress` (L75): `RUN_STRESS_TESTS=true` against integration tests/stress
- `posttest*` hooks (multiple): all run `scripts/cleanup-test-processes.js`
- `pretest:docker` (L43): `scripts/docker-build-if-needed.js`

**Coverage (L76–85):**
- `test:coverage` (L77): full vitest coverage run
- `posttest:coverage` (L78): cleanup + `analyze-coverage.js`
- `test:coverage:analyze` (L82): `analyze-coverage-detailed.js`

**Linting (L96–98):**
- `lint` (L96): ESLint over `src/**/*.ts`, `packages/*/src/**/*.ts`, and `scripts/**/*.{js,mjs,cjs}`
- `lint:fix` (L97): ESLint with auto-fix on `src/**/*.ts`

**Validation & release (L112–116):**
- `validate` (L112): `scripts/validate-push.js`
- `validate:quick` (L113): same with `--no-tests`
- `validate:smoke` (L114): same with `--smoke`
- `release:dry-run` (L116): `bash scripts/release-dry-run.sh`

**CI simulation via `act` (L105–111):** Windows `.cmd` scripts for local GitHub Actions simulation

---

### Dependencies

**Runtime (L142–156):**
| Package | Version | Role |
|---|---|---|
| `@debugmcp/shared` | workspace:* | Internal shared utilities |
| `@modelcontextprotocol/sdk` | ^1.29.0 | MCP server/client SDK |
| `@vscode/debugprotocol` | ^1.68.0 | DAP type definitions |
| `commander` | ^15.0.0 | CLI argument parsing |
| `express` | ^5.2.1 | HTTP server (proxy/API) |
| `winston` | ^3.19.0 | Logging |
| `uuid` | ^14.0.1 | Unique ID generation |
| `lru-cache` | ^11.5.2 | Session/object caching |
| `fs-extra` | ^11.3.6 | Enhanced file system ops |
| `eventsource` | ^4.1.0 | SSE client |
| `debug` | ^4.4.3 | Debug logging utility |
| `which` | ^7.0.0 | Executable path resolution |

**Optional (L157–166):** All language adapter packages (`@debugmcp/adapter-*`) for dotnet, go, java, javascript, mock, python, ruby, rust — all workspace references, optional so missing adapters don't block install.

**Dev (L167–189):**
- `vitest` ^4.1.10 with `@vitest/coverage-istanbul` and `@vitest/coverage-v8`
- `typescript` ^6.0.2, `ts-node` ^10.9.2
- `esbuild` ^0.28.1, `tsup` ^8.5.1
- `eslint` ^10.7.0 with `typescript-eslint` ^8.64.0
- `husky` ^9.1.7 (git hooks via `prepare` script)
- `cross-env` ^10.1.0, `rimraf` ^6.1.3, `fast-check` ^4.9.0

---

### pnpm Configuration (L190–203)
- `onlyBuiltDependencies`: `esbuild` only (security-conscious build step restriction)
- **Security overrides:** `path-to-regexp >=8.4.0`, `brace-expansion >=5.0.6`, `qs ^6.15.2`, `ip-address ^10.1.1` — patch known vulnerabilities in transitive deps
- **Version pins:** `vite 7.3.6`, `hono ^4.12.25`, `fast-uri ^3.1.2`, `esbuild ^0.28.1`

---

### Architectural Notes
- This is the **monorepo root** — not published (`"private": true`, L3)
- Adapter packages are **optional workspace dependencies** enabling graceful degradation when a language adapter isn't installed
- The `nohoist` pattern ensures debugpy (Python) and node-inspector (Node.js) debug tools stay local to their respective adapter packages
- Build pipeline separates concerns: shared lib → adapters → server core → bundle
- Test projects (`unit`, `integration`, `e2e`) are defined in vitest config (not here); this file orchestrates which projects run per command