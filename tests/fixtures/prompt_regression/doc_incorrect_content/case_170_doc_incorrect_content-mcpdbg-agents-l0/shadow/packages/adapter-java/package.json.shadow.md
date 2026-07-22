# packages\adapter-java\package.json
@source-hash: 26d86d939f81c2d4
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:01Z

## Package Manifest: `@debugmcp/adapter-java`

**Version:** 0.22.0 (L3)
**Purpose:** Java debug adapter for MCP Debugger, bridging JDI (Java Debug Interface) to the MCP debugging framework via a JDI bridge component.

### Module System & Entry Points
- ESM-only package (`"type": "module"`, L5)
- Main entry: `./dist/index.js` (L6), types: `./dist/index.d.ts` (L7)
- Exports map (L8–13): single root export `"."` with `import` and `types` conditions pointing to `dist/`

### Distributed Files (L14–17)
- `dist/` — compiled TypeScript output
- `java/` — JDI bridge Java artifacts (compiled via `build:adapter` script)

### Scripts (L18–24)
| Script | Command | Purpose |
|---|---|---|
| `build` | `tsc -p tsconfig.json` | Standard TypeScript compilation |
| `build:ci` | `tsc -p tsconfig.json --noEmitOnError` | CI-safe build (fails on error) |
| `build:adapter` | `node scripts/compile-jdi-bridge.js` | Compiles the Java JDI bridge component |
| `clean` | `rimraf dist java/out` | Removes compiled output for both TS and Java |
| `test` | `vitest run` | Runs tests once (no watch) |

### Dependencies (L25–33)
- **Runtime:**
  - `@debugmcp/shared: workspace:*` (L27) — internal monorepo shared utilities
  - `@vscode/debugprotocol: ^1.68.0` (L28) — DAP (Debug Adapter Protocol) types/interfaces
- **Dev:**
  - `typescript ^5.9.3`, `vitest ^4.1.10`, `@types/node ^26.1.1`, `rimraf ^6.1.3`

### Constraints
- Node.js `>=22.0.0` required (L36–38)

### Repository (L49–53)
- Git: `https://github.com/debugmcp/mcp-debugger.git`, subdirectory `packages/adapter-java`

### Architectural Notes
- Two-phase build: TypeScript (`build`) + Java JDI bridge (`build:adapter`) must both be run for a complete adapter
- The `java/` directory in distributed files indicates pre-compiled Java artifacts are shipped with the package
- Workspace dependency on `@debugmcp/shared` implies monorepo context (pnpm workspace protocol)
- No `peerDependencies` — all runtime deps are direct