# packages\adapter-go\package.json
@source-hash: 0b4bbf52fc2160ba
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:01Z

## Package Manifest: `@debugmcp/adapter-go`

**Version:** 0.22.0 (L3)  
**Purpose:** Go debugging adapter for `mcp-debugger`, integrating with the [Delve](https://github.com/go-delve/delve) debugger via the Debug Adapter Protocol (DAP).

---

### Module Identity (L2–13)
- **Package name:** `@debugmcp/adapter-go`
- **Module type:** ESM (`"type": "module"`, L5)
- **Entry point:** `./dist/index.js` (L6, L10)
- **Type declarations:** `./dist/index.d.ts` (L7, L11)
- **Exports map:** Single `"."` export supporting `import` and `types` conditions (L8–13)
- **Published files:** Only the `dist/` directory is included in the npm package (L14–16)

---

### Build Scripts (L17–23)
| Script | Command | Notes |
|---|---|---|
| `build` | `tsc -p tsconfig.json` | Standard TypeScript compilation |
| `build:ci` | `tsc -p tsconfig.json --noEmitOnError` | CI-safe build; fails without emitting on error |
| `clean` | `rimraf dist` | Removes compiled output |
| `lint` | `eslint src/**/*.ts` | Lints TypeScript sources |
| `test` | `vitest run` | Runs tests once (non-watch mode) |

---

### Dependencies (L24–33)
**Runtime:**
- `@debugmcp/shared`: `workspace:*` (L25) — Internal monorepo shared utilities; version resolved at workspace level
- `@vscode/debugprotocol`: `^1.68.0` (L26) — VS Code DAP type definitions and protocol contracts

**Development:**
- `@types/node`: `^26.1.1` (L29) — Node.js type definitions
- `rimraf`: `^6.1.3` (L30) — Cross-platform directory cleanup
- `typescript`: `^5.9.3` (L31) — TypeScript compiler
- `vitest`: `^4.1.10` (L32) — Test runner

---

### Constraints & Metadata (L34–51)
- **Node.js engine requirement:** `>=22.0.0` (L36) — Requires Node 22+
- **License:** MIT (L46)
- **Repository:** `https://github.com/debugmcp/mcp-debugger.git`, subdirectory `packages/adapter-go` (L47–51)
- **Keywords:** `mcp`, `debugger`, `go`, `golang`, `delve`, `dap` (L37–44)

---

### Architectural Role
This is a **monorepo workspace package** (`workspace:*` on shared dep) within the `mcp-debugger` project. It compiles TypeScript sources in `src/` to `dist/`, consuming `@vscode/debugprotocol` for DAP types and `@debugmcp/shared` for internal shared logic. The adapter bridges the MCP debugger host to Go programs via Delve.