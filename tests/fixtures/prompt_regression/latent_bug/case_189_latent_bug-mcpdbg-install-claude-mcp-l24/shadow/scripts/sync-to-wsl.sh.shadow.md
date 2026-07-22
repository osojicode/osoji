# scripts\sync-to-wsl.sh
@source-hash: c850c6f282c6fc76
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## Purpose
Bash script that syncs the MCP Debugger project from a Windows filesystem to a WSL2 environment, then optionally installs dependencies and builds the project. Intended to be run from within WSL2.

## Usage
```
./scripts/sync-to-wsl.sh [/path/to/project] [--no-install] [--no-build] [--clean]
```

## Key Logic & Flow

### Source Path Auto-Detection (L13–33)
- Determines `WINDOWS_PROJECT_PATH` by inspecting `SCRIPT_DIR` (derived from `BASH_SOURCE[0]`).
- **If running from `/tmp`** (e.g., invoked via a `.cmd` wrapper that copies the script): scans positional arguments for a non-flag argument that is an existing directory (L18–23). If none found, exits with usage error (L24–29).
- **Otherwise**: assumes the script lives inside the project's `scripts/` subdirectory and sets `WINDOWS_PROJECT_PATH` to its parent (L32).
- `WSL_PROJECT_PATH` is hardcoded to `$HOME/debug-mcp-server` (L34).

### Argument Parsing (L43–66)
- `--no-install` → sets `NO_INSTALL=true`, skips `pnpm install`
- `--no-build` → sets `NO_BUILD=true`, skips `npm run build`
- `--clean` → sets `CLEAN_SYNC=true`, deletes destination before sync
- `--help`/`-h` → prints usage and exits

### Sync Steps
1. **Validates** source directory exists (L72–75).
2. **Installs rsync** via apt if missing (L78–81).
3. **Cleans destination** if `--clean` and destination exists (L84–87).
4. **Creates destination** with `mkdir -p` (L90).
5. **rsync** with `--delete`, excluding: `node_modules/`, `dist/`, `coverage/`, `logs/`, `sessions/`, `.npm/`, `*.log`, `*.tmp`, `.DS_Store`, `Thumbs.db`, `package-lock.json`, `integration_test_server_*.log` (L94–107).
6. **Fixes permissions**: `chmod +x scripts/*.sh` (L115).
7. **Checks for `package-lock.json`** absence (excluded from sync), logs informational message (L118–123).
8. **`pnpm install --frozen-lockfile`** unless `--no-install` (L126–131).
9. **`npm run build`** unless `--no-build` (L134–139).
10. Prints success and suggests next steps: `docker build` and `./scripts/act-test.sh ci` (L141–149).

## Notable Patterns & Constraints
- `set -e` (L9): any command failure aborts the script immediately.
- `package-lock.json` is explicitly excluded from rsync (L105) — this conflicts with the comment at L119 mentioning npm install regenerating it, but the actual install command is `pnpm install --frozen-lockfile` (L128), which requires a `pnpm-lock.yaml` (not `package-lock.json`). The check at L118 is therefore informational noise.
- Color escape codes use `echo -e` (L68+); compatible with bash but not POSIX sh.
- The `--frozen-lockfile` flag on pnpm (L128) will fail if `pnpm-lock.yaml` is missing or out of sync — there is no fallback.
- Next-steps output (L147) hardcodes `~/debug-mcp-server`, consistent with `WSL_PROJECT_PATH` (L34).
