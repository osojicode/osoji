# mcp_debugger_launcher\mcp_debugger_launcher\detectors.py
@source-hash: f7b31d12c3a49508
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:16Z

## Purpose
Provides runtime environment detection utilities for the `mcp_debugger_launcher` package. Determines whether Node.js/npx or Docker are available to run `debug-mcp-server`, and recommends the preferred runtime.

## Key Class

### `RuntimeDetector` (L8–163)
Static-method-only class; no instantiation needed. All methods are `@staticmethod`.

| Method | Lines | Purpose |
|---|---|---|
| `check_nodejs()` | L12–31 | Checks `node` on PATH via `shutil.which`, runs `node --version`; returns `(bool, version_str_or_None)` |
| `check_npx()` | L34–36 | Returns `True` if `npx` is found on PATH via `shutil.which` |
| `check_npm_package(package_name)` | L39–51 | Runs `npx --no-install <package_name> --version`; returns `True` if exit code 0 |
| `check_docker()` | L54–95 | Checks `docker` on PATH, runs `docker --version`, then `docker ping` (fallback: `docker ps`); returns `(bool, version_or_status_str)` |
| `check_docker_image(image_name)` | L98–109 | Runs `docker images -q <image_name>`; returns `True` if stdout is non-empty (image exists locally) |
| `detect_available_runtimes()` | L112–150 | Aggregates all checks into a structured dict with keys `"nodejs"` and `"docker"` |
| `get_recommended_runtime(runtimes)` | L153–163 | Accepts the dict from `detect_available_runtimes()`; prefers `"npx"`, falls back to `"docker"`, returns `None` if neither available |

## Return Structure — `detect_available_runtimes()` (L114–126)
```python
{
    "nodejs": {
        "available": bool,
        "version": Optional[str],        # e.g. "v20.11.0"
        "npx_available": bool,
        "package_accessible": bool       # @debugmcp/mcp-debugger via npx --no-install
    },
    "docker": {
        "available": bool,
        "version": Optional[str],        # e.g. "Docker version 24.0.5, ..." or "... (daemon not running)"
        "image_exists": bool             # debugmcp/mcp-debugger:latest present locally
    }
}
```

## Important Behavioral Notes
- **Docker daemon check (L74–91):** Uses `docker ping` as primary check — this is a non-standard Docker subcommand and will typically fail; `docker ps` is the functional fallback. If both fail, Docker is still reported as `available=True` with version string suffixed `" (daemon not running)"`.
- **`get_recommended_runtime` does NOT require `package_accessible=True`** (L156–158): npx is recommended as long as Node.js and npx exist, regardless of whether `@debugmcp/mcp-debugger` is actually accessible.
- All subprocess calls use `capture_output=True` and bounded `timeout` values (5s or 10s) to prevent hangs.
- Exceptions (`TimeoutExpired` and catch-all `Exception`) are silently swallowed in all check methods.

## Hardcoded Package/Image Names
- npm package: `"@debugmcp/mcp-debugger"` (L137)
- Docker image: `"debugmcp/mcp-debugger:latest"` (L147)

## Dependencies
- `subprocess` — process execution
- `shutil.which` — PATH lookup
- `os` — imported but unused
- `typing.Tuple`, `typing.Optional` — type hints
