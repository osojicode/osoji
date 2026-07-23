# packages\mcp-debugger\package.json
@source-hash: 97b27393e9946229
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:31Z

## Package: `@debugmcp/mcp-debugger` (v0.22.0)

### Purpose
This is the root package manifest for the `mcp-debugger` package — a step-through debugging MCP (Model Context Protocol) server designed for LLMs. It defines the publishable NPM package that bundles all language-specific debug adapters into a single distributable CLI binary.

### Key Configuration

**Package Identity (L2–L4)**
- Name: `@debugmcp/mcp-debugger`
- Version: `0.22.0`
- Module type: ESM (`"type": "module"`, L12)
- Node engine requirement: `>=22.0.0` (L22–L23) — strictly modern Node only

**CLI Entry Point (L13–L15)**
- Exposes a binary named `mcp-debugger` mapped to `./dist/cli`
- The `dist/` directory is the compiled output target

**Published Files (L16–L20)**
- Only `dist/`, `README.md`, and `LICENSE` are included in the NPM publish — source files are excluded

**Build Scripts (L24–L28)**
- `build` and `build:ci` both run `node scripts/bundle-cli.js` — the bundler script is the single build entrypoint
- `clean` removes `dist/` and TypeScript build info via `rimraf`

### Dependency Architecture

**Zero runtime dependencies (L32)**
- `"dependencies": {}` — the published package has no npm runtime deps; everything is bundled at build time via `scripts/bundle-cli.js`

**Dev/Build-time workspace dependencies (L33–L43)**
All are internal monorepo workspace packages (`workspace:*`):
- `@debugmcp/adapter-dotnet` — .NET debug adapter
- `@debugmcp/adapter-go` — Go debug adapter
- `@debugmcp/adapter-javascript` — JavaScript/Node debug adapter
- `@debugmcp/adapter-python` — Python debug adapter
- `@debugmcp/adapter-mock` — Mock adapter (testing/dev)
- `@debugmcp/adapter-ruby` — Ruby debug adapter
- `@debugmcp/adapter-rust` — Rust debug adapter
- `@debugmcp/adapter-java` — Java debug adapter
- `@debugmcp/shared` — Shared utilities/types across the monorepo

### Architectural Notes
- This is a **bundled distribution package**: all workspace adapters are devDependencies consumed at bundle time, so the final `dist/cli` artifact is self-contained with no npm install requirements at runtime.
- The `publishConfig.access: "public"` (L29–L31) means this scoped package is published publicly to the npm registry.
- Located at `packages/mcp-debugger` within the monorepo (L9).
- Repository: `https://github.com/debugmcp/mcp-debugger` (L8)