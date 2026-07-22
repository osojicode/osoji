# scripts\check-adapters.js
@source-hash: 1c299f30347c5903
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:39Z

## Purpose
CLI script that inspects the local filesystem to report vendoring status of debug adapters (JavaScript/js-debug and Rust/CodeLLDB). Exits with code 1 if any adapter is missing on the current platform (unless in CI).

## Architecture & Flow

### Module-level setup (L12–32)
- Resolves `__dirname` via ESM `fileURLToPath` pattern (L12–14)
- `rootDir` = one level above `scripts/` (L14)
- `adapters` array (L17–32): static configuration driving all checks. Two entries:
  - **JavaScript**: checks `packages/adapter-javascript/vendor/js-debug/vsDebugServer.js` plus sidecar files `bootloader.js`, `hash.js`; reads version from `manifest.json`
  - **Rust**: checks `packages/adapter-rust/vendor/codelldb/<platform>/adapter/codelldb[.exe]`; reads version from `<platform>/version.json`

### Adapter dispatch (L235–242)
`main()` dispatches by `adapter.name.includes('JavaScript')` / `adapter.name.includes('Rust')`. New adapters in the `adapters` array that don't match either string will be skipped with a warning.

### Key functions

| Function | Lines | Role |
|---|---|---|
| `getCurrentPlatform()` | L37–48 | Maps `process.platform`+`process.arch` to string like `darwin-arm64` |
| `exists(filePath)` | L53–60 | Filesystem presence check via `fs.accessSync` |
| `readJsonSafe(filePath)` | L65–71 | Safe JSON parse; returns `null` on any error |
| `checkJavaScriptAdapter(adapter)` | L76–116 | Builds status object: vendored bool, version, sidecars map, issues array |
| `checkRustAdapter(adapter)` | L121–166 | Builds status object with per-platform breakdown; marks `vendored=true` only if current platform is present |
| `formatStatus(status)` | L171–218 | Renders ANSI-colored console output; handles both JS (sidecars) and Rust (platforms) status shapes |
| `main()` | L223–272 | Orchestrates checks, prints summary, calls `process.exit(1)` on failure unless `CI=true` |

### Status object shapes
**JavaScript status** (L81–87):
```
{ name, vendored, version, source, sidecars: {filename: bool}, issues: [] }
```
**Rust status** (L126–132):
```
{ name, vendored, currentPlatform, version, platforms: {name: {vendored, version?, current}}, issues: [] }
```

### Exit behavior (L269–271)
- Exits 1 if any adapter not vendored AND `process.env.CI !== 'true'`
- Designed to be invocable both as a script and as an imported module (L274–278)

## Notable Patterns
- **Direct invocation guard** (L274–278): compares `process.argv[1]` resolved path to `__filename` — safe ESM equivalent of CommonJS `require.main === module`
- **Adapter type dispatch by name string** (L235–237): brittle — relies on adapter `name` field containing literal substrings "JavaScript" and "Rust"
- **Platform detection is exhaustive for known targets** (L41–46); unknown combos fall through to `${platform}-${arch}` (L47)
- The Rust adapter `versionFile: null` comment (L29) is accurately documented — version is read per-platform from `version.json` inside each platform directory instead
