# mcp_debugger_launcher\pyproject.toml
@source-hash: 0ffa4d22f90cb4e6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:27Z

## Purpose
Python package configuration for `debug-mcp-server-launcher` (v0.17.0). This is a **launcher/shim package** that ensures `debugpy` is installed in the Python environment and exposes a CLI entry point (`debug-mcp-server`) that delegates to `mcp_debugger_launcher.cli:main`. The actual MCP debug server runs under Node.js or Docker — this package only handles the Python-side dependency installation and CLI bootstrapping.

## Key Metadata
- **Package name:** `debug-mcp-server-launcher` (L2)
- **Version:** `0.17.0` (L3)
- **Python requirement:** `>=3.8` (L6); supports 3.8–3.11 per classifiers (L16–19)
- **License:** MIT (L7)
- **Author:** debugmcp / debug@sycamore.llc (L9)
- **Keywords:** mcp, dap, debugger, debugpy, ai-agent, llm (L11)
- **Development Status:** Alpha (L13)

## Runtime Dependencies (L23–26)
| Package | Constraint | Role |
|---|---|---|
| `debugpy` | `>=1.8.14` | Core Python debugger adapter (DAP protocol) |
| `click` | `>=8.0.0` | CLI framework used by `mcp_debugger_launcher.cli` |

## Entry Points (L32–33)
- **CLI script:** `debug-mcp-server` → `mcp_debugger_launcher.cli:main`
  - Installed as a system/venv executable when the package is installed via pip.

## Build System (L35–37)
- Backend: `setuptools.build_meta`
- Requires: `setuptools>=61.0`, `wheel`

## Package Layout (L39–43)
- Only package included: `mcp_debugger_launcher` (L40)
- Package data: `LICENSE` file bundled inside `mcp_debugger_launcher/` (L43)

## Upstream Repository
- GitHub: `https://github.com/debugmcp/mcp-debugger` (L29–30)

## Architectural Role
This is a thin **entry** / launcher package. The package's sole job is to (1) pull `debugpy` into the environment as a dependency and (2) provide the `debug-mcp-server` CLI command. Business logic lives in `mcp_debugger_launcher/cli.py`.