# mcp_debugger_launcher\mcp_debugger_launcher\detectors.py
@source-hash: f7b31d12c3a49508
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:03Z

## Purpose
Provides runtime detection utilities for the `mcp_debugger_launcher` package. Determines which runtimes (Node.js/npx or Docker) are available on the host system and recommends the preferred one for launching `debug-mcp-server`.

## Key Class: `RuntimeDetector` (L8–163)
Stateless utility class — all methods are `@staticmethod`. No instantiation needed.

### Methods

| Method | Lines | Description |
|---|---|---|
| `check_nodejs()` | L12–31 | Runs `node --version`, returns `(available: bool, version: str | None)` |
| `check_npx()` | L34–36 | Checks `npx` on PATH via `shutil.which`; returns `bool` |
| `check_npm_package(package_name)` | L39–51 | Runs `npx --no-install <package> --version`; returns `bool` |
| `check_docker()` | L54–95 | Runs `docker --version` + daemon liveness check; returns `(available, version)` |
| `check_docker_image(image_name)` | L98–109 | Runs `docker images -q <image>`; returns `bool` |
| `detect_available_runtimes()` | L112–150 | Aggregates all checks into a dict; checks `@debugmcp/mcp-debugger` (L136–138) and `debugmcp/mcp-debugger:latest` (L146–148) |
| `get_recommended_runtime(runtimes)` | L153–163 | Prefers `"npx"` if Node+npx available; falls back to `"docker"`; returns `None` if neither viable |

## Runtime Detection Logic
1. **Node.js path**: `check_nodejs` → `check_npx` → `check_npm_package("@debugmcp/mcp-debugger")`
2. **Docker path**: `check_docker` → `check_docker_image("debugmcp/mcp-debugger:latest")`
3. Daemon liveness fallback: `docker ping` (L74–79), then `docker ps` (L83–88). Returns `True, "<version> (daemon not running)"` if CLI exists but daemon is unresponsive (L90).

## Return Shape of `detect_available_runtimes()`
```python
{
    "nodejs": {
        "available": bool,
        "version": str | None,
        "npx_available": bool,
        "package_accessible": bool
    },
    "docker": {
        "available": bool,
        "version": str | None,
        "image_exists": bool
    }
}
```

## Runtime Recommendation Priority
`get_recommended_runtime` (L153–163):
- Returns `"npx"` if `nodejs.available` AND `nodejs.npx_available` (does NOT require `package_accessible`)
- Returns `"docker"` if `docker.available` AND daemon is running
- Returns `None` otherwise

## Subprocess Timeouts
- `node --version`: 5s
- `npx --no-install ... --version`: 10s
- `docker --version`, `docker ping`, `docker ps`, `docker images`: 5s each

## Dependencies
- `subprocess` (stdlib) — process execution
- `shutil.which` — PATH-based binary lookup
- `os` — imported but unused

## Notable Patterns
- All subprocess calls use `capture_output=True, text=True` (no stdout/stderr leak)
- Broad exception catching `except (subprocess.TimeoutExpired, Exception)` covers all failure modes silently
- `detect_available_runtimes` only checks `package_accessible` if `npx_available` is also true (L135 guard)
- Docker daemon liveness: `docker ping` is non-standard; real daemon check relies on `docker ps` fallback