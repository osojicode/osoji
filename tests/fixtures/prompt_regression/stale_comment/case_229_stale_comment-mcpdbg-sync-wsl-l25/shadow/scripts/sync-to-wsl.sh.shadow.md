# scripts\sync-to-wsl.sh
@source-hash: f1d76c942c3fc34f
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:21Z

## Purpose
Bash script that syncs the MCP Debugger project from a Windows filesystem into a WSL2 Linux environment, then optionally installs dependencies and builds the project. Intended to be run from within WSL2.

## Execution Flow

1. **Auto-detect source path (L13–33):** Determines `WINDOWS_PROJECT_PATH` by inspecting `SCRIPT_DIR`. If the script is running from `/tmp` (i.e., copied by a `.cmd` wrapper), it scans positional arguments for a valid directory path; exits with error if none found. Otherwise, it uses the parent of the script's directory.
2. **Fixed WSL destination (L34):** `WSL_PROJECT_PATH` is always `$HOME/debug-mcp-server`.
3. **Argument parsing (L43–66):** Flags `--no-install`, `--no-build`, `--clean`, `--help`/`-h`. Non-flag positional args used earlier for path detection.
4. **Prerequisite checks (L71–81):** Verifies Windows source dir exists; auto-installs `rsync` via `apt-get` if missing.
5. **Optional clean (L84–87):** Removes existing WSL destination with `rm -rf` if `--clean` and destination exists.
6. **rsync sync (L90–107):** Creates destination dir, then rsyncs with `--delete` and extensive exclusions (node_modules, dist, coverage, logs, sessions, .npm, *.log, *.tmp, .DS_Store, Thumbs.db, package-lock.json, integration_test_server_*.log).
7. **Permission fix (L115):** Runs `chmod +x scripts/*.sh` — errors silently suppressed.
8. **Install (L118–123):** Runs `pnpm install --frozen-lockfile` unless `--no-install`.
9. **Build (L126–131):** Runs `npm run build` unless `--no-build`.
10. **Next-steps hint (L136–141):** Prints suggested docker build and act-test commands.

## Key Variables
| Variable | Line | Description |
|---|---|---|
| `SCRIPT_DIR` | 13 | Resolved directory of the script |
| `WINDOWS_PROJECT_PATH` | 17/32 | Source path on Windows/WSL mount |
| `WSL_PROJECT_PATH` | 34 | Always `$HOME/debug-mcp-server` |
| `NO_INSTALL` | 43 | Skip `pnpm install` when true |
| `NO_BUILD` | 44 | Skip `npm run build` when true |
| `CLEAN_SYNC` | 45 | Wipe destination before sync when true |

## Notable Patterns / Constraints
- `set -e` (L9) means any unhandled non-zero exit aborts the script immediately.
- Uses `pnpm install` (L120) for dependency installation but `npm run build` (L128) for building — mixed package manager usage.
- The `package-lock.json` exclusion (L105) combined with `pnpm install --frozen-lockfile` implies the project uses `pnpm-lock.yaml`, not `package-lock.json`.
- The `/tmp` detection path (L15–29) supports a `.cmd` wrapper pattern where the script is temporarily copied before invocation.
- rsync `--delete` flag (L94) means files present in WSL but not in Windows source will be deleted (subject to exclusions).
