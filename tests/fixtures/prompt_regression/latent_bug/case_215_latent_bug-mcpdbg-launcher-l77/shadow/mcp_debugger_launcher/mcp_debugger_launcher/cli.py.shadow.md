# mcp_debugger_launcher\mcp_debugger_launcher\cli.py
@source-hash: 176a43208f2894d3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:21Z

## Purpose
CLI entry point for the `mcp-debugger-launcher` package. Provides a Click-based command (`debug-mcp-server`) that detects available runtimes (Node.js/npx or Docker), validates options, and delegates server launch to `DebugMCPLauncher`.

## Key Symbols

### `main` (L82–199) — Click command, public entry point
Primary CLI handler. Orchestrates:
1. `check_debugpy()` backward-compatibility check (L97–103)
2. Conflict detection for `--docker`/`--npm` flags (L106–108)
3. Runtime detection via `RuntimeDetector.detect_available_runtimes()` (L114)
4. Runtime selection: forced (`--docker`/`--npm`) or auto via `RuntimeDetector.get_recommended_runtime()` (L143)
5. Dry-run path — prints command without executing (L163–168, L182–191)
6. Actual launch via `launcher.launch_with_npx(mode, port)` (L179) or `launcher.launch_with_docker(mode, port)` (L197)

**Parameters:**
- `mode` — `'stdio'` (default) or `'sse'` (Click `Choice`)
- `port` — optional int for SSE port
- `docker` / `npm` — mutually exclusive runtime forcing flags
- `dry_run` — prints resolved command without executing
- `verbose` — enables extra runtime status output

**Return values:** integer exit codes (0, 1) but Click command doesn't explicitly propagate them — `sys.exit(main())` at L202 handles this only for direct execution.

### `print_runtime_status` (L19–51) — internal helper
Formats and prints Node.js and Docker availability with nested detail in verbose mode. Reads keys: `nodejs.available`, `nodejs.version`, `nodejs.npx_available`, `nodejs.package_accessible`, `docker.available`, `docker.version`, `docker.image_exists`.

### `print_installation_help` (L53–62) — internal helper
Prints static installation guidance for Node.js and Docker. No parameters.

### `check_debugpy` (L64–72) — internal helper
Attempts `import debugpy` and returns `(bool, version_str | None)`. Returns `(True, "unknown")` if `AttributeError` on `__version__`.

### `__version__` (L17)
`"0.11.1"` — must stay in sync with `pyproject.toml`.

## Import Strategy (L9–14)
Dual import pattern supports both package install (`from .launcher import ...`) and direct script execution (`from launcher import ...`).

## Dependencies
- `DebugMCPLauncher` — provides `launch_with_npx(mode, port)`, `launch_with_docker(mode, port)`, class constants `DEFAULT_SSE_PORT`, `NPM_PACKAGE`, `DOCKER_IMAGE`
- `RuntimeDetector` — provides `detect_available_runtimes() -> dict`, `get_recommended_runtime(runtimes) -> str | None`
- `click` — command definition, option/argument parsing, version option

## Runtime Dict Contract
Both `print_runtime_status` and `main` expect `runtimes` with this shape:
```python
{
  "nodejs": {"available": bool, "version": str, "npx_available": bool, "package_accessible": bool},
  "docker": {"available": bool, "version": str, "image_exists": bool}
}
```

## Notable Patterns
- `return 1` inside a Click command (L108, L122, L126, L132, L136, L149) does **not** cause a non-zero process exit unless caught by `sys.exit(main())` at L202. When invoked via `click` (normal CLI), Click ignores non-`SystemExit` return values, so these error paths silently succeed at the process level.
- Version string at L17 is a single source of truth for `--version`/`-V` flag (L81).