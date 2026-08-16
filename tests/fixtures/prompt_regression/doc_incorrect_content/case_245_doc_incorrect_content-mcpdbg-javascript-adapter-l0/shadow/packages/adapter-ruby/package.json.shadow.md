# packages\adapter-ruby\package.json
@source-hash: d63426355f91b6fa
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:44Z

## Package Manifest: `@debugmcp/adapter-ruby`

**File:** `packages/adapter-ruby/package.json`

### Purpose
NPM package manifest for the Ruby debug adapter within the `debugmcp` monorepo. Integrates Ruby debugging via `rdbg` (Ruby Debug gem) into the MCP debugger framework.

### Key Metadata
- **Package name:** `@debugmcp/adapter-ruby` (L2)
- **Version:** `0.22.0` (L3)
- **Module type:** ESM (`"type": "module"`, L5)
- **Entry point:** `dist/index.js` (L6); TypeScript declarations at `dist/index.d.ts` (L7)
- **Published files:** Only the `dist/` directory is included in the npm package (L8–10)

### Scripts (L11–17)
| Script | Command | Purpose |
|---|---|---|
| `build` | `tsc -b` | Incremental TypeScript project build |
| `build:ci` | `tsc -b -f` | Force full TypeScript build (CI environments) |
| `clean` | `rimraf dist && rimraf tsconfig.tsbuildinfo` | Remove build artifacts |
| `test` | `vitest run` | Single-pass test run |
| `test:watch` | `vitest watch` | Watch-mode test run |

### Runtime Dependencies (L18–22)
- **`@debugmcp/shared`** (`workspace:*`, L19): Internal monorepo shared utilities/types — resolved as workspace peer
- **`@vscode/debugprotocol`** (`^1.68.0`, L20): VS Code Debug Adapter Protocol (DAP) type definitions and protocol support
- **`which`** (`^7.0.0`, L21): Executable path resolution (used to locate `rdbg` on the system PATH)

### Dev Dependencies (L23–28)
- `@types/node` `^26.1.1` — Node.js type definitions
- `@types/which` `^3.0.4` — Type definitions for `which`
- `typescript` `^5.9.3` — TypeScript compiler
- `vitest` `^4.1.10` — Test runner

### Engine Constraint (L29–31)
- Requires **Node.js >= 22.0.0** — enforces modern Node with native ESM and built-in APIs

### Peer Dependencies (L32–34)
- **`@debugmcp/shared`** pinned at exact version `0.22.0` — must match the monorepo release version; declared as both a runtime dependency (`workspace:*`) and peer dependency (exact `0.22.0`) to enforce version alignment for external consumers

### Repository (L35–39)
- GitHub: `https://github.com/debugmcp/mcp-debugger.git`
- Monorepo subdirectory: `packages/adapter-ruby`

### Publish Config (L40–42)
- `"access": "public"` — package is published publicly to the npm registry (scoped packages default to private)

### Architectural Notes
- Part of a monorepo using pnpm workspace protocol (`workspace:*`)
- Follows the monorepo adapter pattern: each language adapter is a separate scoped package
- Build pipeline uses TypeScript project references (`tsc -b`), implying a root `tsconfig.json` with project references
- No bundler (esbuild/rollup) — ships raw TypeScript compiler output
