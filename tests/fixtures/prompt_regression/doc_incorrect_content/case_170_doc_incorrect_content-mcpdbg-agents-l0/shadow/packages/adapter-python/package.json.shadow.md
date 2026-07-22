# packages\adapter-python\package.json
@source-hash: bc84261e6aaee8e1
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:05Z

## `packages/adapter-python/package.json`

### Purpose
NPM package manifest for `@debugmcp/adapter-python` (v0.22.0) — the Python debug adapter for the MCP debugger project, implemented using `debugpy`.

### Key Fields

- **Package name:** `@debugmcp/adapter-python` (L2) — scoped under `@debugmcp` org
- **Version:** `0.22.0` (L3) — must stay in sync with `@debugmcp/shared` peer dependency (L33)
- **Module type:** ESM (`"type": "module"`, L5)
- **Entry point:** `dist/index.js` (L6); types at `dist/index.d.ts` (L7)
- **Published files:** only `dist/` directory (L8–10)

### Scripts (L11–17)
| Script | Command | Purpose |
|---|---|---|
| `build` | `tsc -b` | Incremental TypeScript project build |
| `build:ci` | `tsc -b -f` | Force full rebuild (CI use) |
| `clean` | `rimraf dist && rimraf tsconfig.tsbuildinfo` | Remove build artifacts |
| `test` | `vitest run` | Single-run test suite |
| `test:watch` | `vitest watch` | Watch-mode testing |

### Dependencies (L18–22)
- **`@debugmcp/shared`** (`workspace:*`, L19) — sibling monorepo package; provides shared types/utilities. Pinned to exactly `0.22.0` as a peer dependency (L33).
- **`@vscode/debugprotocol`** (`^1.68.0`, L20) — DAP (Debug Adapter Protocol) type definitions from VS Code.
- **`which`** (`^7.0.0`, L21) — Used to locate Python/debugpy executables on PATH.

### Dev Dependencies (L23–28)
- `@types/node` `^26.1.1` — Node.js type definitions
- `@types/which` `^3.0.4` — Types for the `which` package
- `typescript` `^5.9.3` — Compiler
- `vitest` `^4.1.10` — Test framework

### Constraints & Notes
- **Node engine:** `>=22.0.0` (L30–31) — requires modern Node.js
- **Peer dependency:** `@debugmcp/shared` must be exactly `0.22.0` (L33) — tight version coupling within the monorepo
- **Publish:** public npm access (L40–42)
- **Repository:** `git+https://github.com/debugmcp/mcp-debugger.git`, subdirectory `packages/adapter-python` (L35–39)

### Monorepo Context
This package is part of a pnpm workspace (`workspace:*` dependency). It depends on `@debugmcp/shared` as both a workspace dependency and a pinned peer, indicating the two packages are versioned together and must match exactly at `0.22.0`.