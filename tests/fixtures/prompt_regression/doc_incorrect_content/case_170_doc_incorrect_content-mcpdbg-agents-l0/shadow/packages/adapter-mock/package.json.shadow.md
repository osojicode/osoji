# packages\adapter-mock\package.json
@source-hash: 33b5b6f1df74fa1b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:03Z

## Package Manifest: `@debugmcp/adapter-mock`

**File:** `packages/adapter-mock/package.json`

### Overview
Package manifest for the mock debug adapter used in testing the MCP debugger. This is an ESM-only package (`"type": "module"`, L5) that ships compiled TypeScript output.

### Identity & Distribution
- **Package name:** `@debugmcp/adapter-mock` (L2)
- **Version:** `0.22.0` (L3) — must stay in sync with peer dependency constraint on `@debugmcp/shared` (L31)
- **Description:** "Mock debug adapter for testing MCP debugger" (L4)
- **Published dist:** `dist/` directory only (L9), entry `dist/index.js` (L6), types `dist/index.d.ts` (L7)
- **Public registry access:** `publishConfig.access: "public"` (L39)

### Module System
- ESM (`"type": "module"`, L5); consumers must use ESM-compatible import resolution.
- **Node.js engine requirement:** `>=22.0.0` (L29)

### Build & Scripts (L11–L17)
| Script | Command | Purpose |
|---|---|---|
| `build` | `tsc -b` | Incremental TypeScript project build |
| `build:ci` | `tsc -b -f` | Force full rebuild (CI) |
| `clean` | `rimraf dist && rimraf tsconfig.tsbuildinfo` | Remove build artifacts |
| `test` | `vitest run` | Single-run test suite |
| `test:watch` | `vitest watch` | Watch mode tests |

### Dependencies (L18–L26)
| Dep | Version | Role |
|---|---|---|
| `@debugmcp/shared` | `workspace:*` (runtime), `0.22.0` (peer) | Shared monorepo types/utilities |
| `@vscode/debugprotocol` | `^1.68.0` | DAP (Debug Adapter Protocol) type definitions |
| `@types/node` | `^26.1.1` | Node.js type definitions (dev) |
| `typescript` | `^5.9.3` | TypeScript compiler (dev) |
| `vitest` | `^4.1.10` | Test runner (dev) |

### Monorepo Context
- Workspace dependency on `@debugmcp/shared` via `workspace:*` (L19); pinned peer to exact version `0.22.0` (L31) — both must be updated together on version bumps.
- Repository: `https://github.com/debugmcp/mcp-debugger.git`, subdirectory `packages/adapter-mock` (L33–L37).

### Architectural Notes
- This package is a **test/mock adapter**, not a production adapter. It depends on `@vscode/debugprotocol` to implement or stub the DAP interface for use in integration/unit tests of the broader MCP debugger system.
- No runtime peer on `@vscode/debugprotocol` — consumers are expected to provide it transitively or directly.