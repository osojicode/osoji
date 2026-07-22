# scripts\prepare-pack.js
@source-hash: f1abebf410c30a8b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:10Z

## Purpose
CLI script that prepares `packages/mcp-debugger/package.json` for `npm pack` by resolving `workspace:` protocol dependency references to concrete version numbers, mimicking what `pnpm publish` does automatically. Supports two commands: `prepare` (mutate package.json, backup original) and `restore` (revert from backup).

## Key Symbols

### `getWorkspaceVersions` (L27–43)
Scans a hardcoded list of 9 workspace packages under `../packages/` and builds a `{ packageName: version }` map by reading each `package.json`. Silently skips packages whose `package.json` does not exist on disk.

**Hardcoded workspace list (L32):** `shared`, `adapter-dotnet`, `adapter-go`, `adapter-java`, `adapter-javascript`, `adapter-python`, `adapter-mock`, `adapter-ruby`, `adapter-rust`

### `resolveWorkspaceDeps(pkg, versions)` (L46–85)
Clones the package object and resolves any dependency whose version string starts with `workspace:` to the exact version from the `versions` map. Processes `dependencies`, `devDependencies`, and `peerDependencies`. Throws `Error` if a workspace dep name is not found in the versions map (L59). Note: replaces with bare version number (not semver-prefixed), discarding any `workspace:^`, `workspace:~`, or `workspace:*` range semantics.

### `main` (L87–136)
Entry point. Reads `process.argv[2]` for the command:
- `prepare` (L90–119): Guards against stale backup (auto-restores if backup exists, L93–98), backs up original `package.json` to `package.json.backup`, resolves workspace deps, writes updated `package.json`.
- `restore` (L121–130): Copies backup back to `package.json` and deletes backup; warns if no backup found.
- Any other value: prints usage and exits with code 1 (L132–135).

## File Paths (Module-Level Constants)
| Constant | Value |
|---|---|
| `PACKAGE_DIR` (L14) | `<repo_root>/packages/mcp-debugger` |
| `PACKAGE_JSON` (L15) | `PACKAGE_DIR/package.json` |
| `BACKUP_JSON` (L16) | `PACKAGE_DIR/package.json.backup` |

## Architectural Notes
- ESM script (`import` syntax, `import.meta.url` for `__dirname` emulation, L11–12).
- `log` (L18–20) and `warn` (L22–24) are thin wrappers prefixing `[prepare-pack]` to stdout/stderr.
- The script is idempotent for `prepare`: a leftover backup from a prior interrupted run is automatically cleaned up before proceeding (L93–98).
- Workspace resolution always produces exact version strings (no semver range prefix), which may differ from the intended pinning semantics of `workspace:^` or `workspace:~`.
- `main` is called at module-level (L138–141) with a top-level `.catch` that prints the error and exits with code 1.

## Usage
```sh
node scripts/prepare-pack.js prepare   # before npm pack
node scripts/prepare-pack.js restore   # after npm pack
```
