# packages\adapter-rust\package.json
@source-hash: ea024e60b1111293
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:52Z

## Package Manifest: `@debugmcp/adapter-rust`

**Version:** 0.22.0 (L3)
**Description:** Rust debug adapter for MCP Debugger using CodeLLDB (L4)

### Module System & Entry Points
- ESM-only package (`"type": "module"`, L5)
- Main entry: `./dist/index.js` (L6); types: `./dist/index.d.ts` (L7)
- Exports map (L8–13): single root export `"."` with `import` and `types` conditions — no CJS fallback

### Published Files (L14–17)
- `dist/` — compiled TypeScript output
- `vendor/` — vendored CodeLLDB binaries (populated by `build:adapter` script)

### Scripts (L18–26)
| Script | Command | Purpose |
|---|---|---|
| `build` / `build:ci` | `tsc -p tsconfig.json` | TypeScript compilation (identical, L19–20) |
| `build:adapter` | `node scripts/vendor-codelldb.js` | Downloads/vendors CodeLLDB debug adapter binary |
| `clean` | `rimraf dist vendor` | Removes both compiled output and vendored binaries |
| `clean:vendor` | `rimraf vendor` | Removes only vendored binaries |
| `test` / `test:watch` | `vitest run` / `vitest watch` | Unit test execution via Vitest |

### Runtime Dependencies (L27–31)
- `@debugmcp/shared: workspace:*` — internal shared utilities (workspace monorepo sibling)
- `@vscode/debugprotocol: ^1.68.0` — DAP (Debug Adapter Protocol) type definitions
- `which: ^7.0.0` — executable lookup utility (used to locate system tools like `lldb`)

### Dev Dependencies (L32–40)
- `extract-zip: ^2.0.1` — used by `vendor-codelldb.js` to unpack CodeLLDB release archives
- `progress: ^2.0.3` — CLI progress bar for download feedback in vendor script
- `typescript: ^5.9.3`, `vitest: ^4.1.10`, `rimraf: ^6.1.3`, `@types/node: ^26.1.1`, `@types/which: ^3.0.4`

### Engine Constraint (L41–43)
- Requires Node.js >= 22.0.0

### Architectural Notes
- `build:adapter` is a **separate, explicit step** from TypeScript compilation — CodeLLDB vendoring is not automatic on `build`. CI pipelines must invoke it independently to populate `vendor/`.
- `build` and `build:ci` are identical (L19–20), suggesting a potential future divergence point or an artifact of scaffolding.
- The package is a monorepo member consuming `@debugmcp/shared` via workspace protocol.