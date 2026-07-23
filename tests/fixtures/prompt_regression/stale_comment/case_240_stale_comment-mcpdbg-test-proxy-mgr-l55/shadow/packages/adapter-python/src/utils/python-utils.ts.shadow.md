# packages\adapter-python\src\utils\python-utils.ts
@source-hash: b7fda1aff64cc5cb
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:56Z

## Python Executable Detection Utilities

Provides cross-platform Python executable discovery for the `adapter-python` package. Handles Windows-specific edge cases (Store aliases, PATH case-sensitivity, `ComSpec` absence), GitHub Actions CI environments, and `debugpy` availability ranking.

### Key Symbols

#### `CommandNotFoundError` (L24–31)
Custom error class thrown when `which` cannot locate a command. Has a `command: string` field for the searched command name. Used as a discriminant in `findPythonExecutable` catch blocks to distinguish "not found" from unexpected errors.

#### `CommandFinder` interface (L33–38)
Abstraction over command location. Single method: `find(cmd, platform?)`. `platform` defaults to `process.platform`; accepts override for testing (issue #186).

#### `WhichCommandFinder` (L40–221) — internal
Production implementation of `CommandFinder` using the `which` npm library. Key behaviors:
- **Caching** (L41–47): opt-in per-instance `Map<string, string>` cache; defaults enabled.
- **Windows ComSpec fix** (L54–63): Synthesizes `ComSpec`/`COMSPEC` from `SystemRoot`/`windir` if absent.
- **PATH case fix** (L96–101): Copies `process.env.Path` → `process.env.PATH` when the uppercase variant is absent (Windows case-insensitive env).
- **Windows Store alias filtering** (L104–118): Regex `/\\microsoft\\windowsapps\\(python(\d+)?|py)\.exe$/` filters out Store shim paths from `which --all` results.
- **`.exe` fallback** (L126–136): If `which(cmd)` fails on Windows, retries with `${cmd}.exe`.
- **Verbose diagnostics** (L66–94, L164–217): Enabled via `DEBUG_PYTHON_DISCOVERY=true`; logs PATH entries and attempts a direct `spawn(cmd, ['--version'])` with 2-second timeout to diagnose `which` failures.

#### `setDefaultCommandFinder(finder)` (L230–234) — exported
Replaces the module-level `defaultCommandFinder`; returns the previous instance. Used in tests to inject mocks.

#### `resetDefaultCommandFinder()` (L242–244) — exported
Reinstates a fresh `WhichCommandFinder()` (empty cache), preventing test state leakage between randomized test runs.

#### `isValidPythonExecutable(pythonCmd, logger?)` (L249–276) — internal
Spawns `python -c 'import sys; sys.exit(0)'` and checks exit code. Returns `false` for Windows Store aliases (detected via exit code 9009 or stderr containing `Microsoft Store`, `Windows Store`, or `AppData\Local\Microsoft\WindowsApps`). Only called on Windows paths.

#### `hasDebugpy(pythonPath, logger?)` (L281–299) — internal
Spawns `python -c 'import debugpy; print(debugpy.__version__)'`. Returns `true` if exit code is 0 and stdout is non-empty. Used to prefer a Python installation that already has `debugpy` available.

#### `findPythonExecutable(preferredPath?, logger?, commandFinder?, platform?)` (L308–484) — **primary export**
Five-stage discovery pipeline:
1. **User-specified path** (L351–366): If `preferredPath` given, resolve via `commandFinder.find()` and validate on Windows; return immediately on success.
2. **Environment variables** (L369–385): Checks `PYTHON_PATH` then `PYTHON_EXECUTABLE`.
3. **GitHub Actions `pythonLocation`** (L387–416): Checks `process.env.pythonLocation` / `PythonLocation`; constructs OS-appropriate candidate paths under that directory; validates existence with `fs.existsSync`.
4. **Auto-detect** (L419–440): Tries `['py','python','python3']` on Windows or `['python3','python']` on other platforms; collects all valid paths into `validPythonPaths`.
5. **debugpy preference** (L443–459): Returns first Python in `validPythonPaths` that has `debugpy`; falls back to first valid Python if none do.
Throws `Error` with human-readable path list if no Python found at all. On failure in CI, logs structured JSON via `logger.error`.

#### `getPythonVersion(pythonPath)` (L489–508) — exported
Spawns `python --version`, reads combined stdout+stderr (Python 2 writes version to stderr). Extracts `\d+\.\d+\.\d+` via regex; falls back to sanitized first line of output via `sanitizeStderr`. Returns `null` on error or no match.

### Dependencies
- `which`: npm package for PATH-based command resolution (`{ all: true }` to get all matches)
- `child_process.spawn`: used for validation spawns (`isValidPythonExecutable`, `hasDebugpy`, `getPythonVersion`)
- `node:fs`: `fs.existsSync` for `pythonLocation` candidate checks
- `node:path`: path construction for `pythonLocation` and `ComSpec` fallback
- `@debugmcp/shared`: `sanitizeStderr`, `sanitizeStderrTail` — used to redact potentially sensitive child process output before logging

### Notable Patterns
- **`defaultCommandFinder` module variable** (L224): Mutable singleton allows test injection without touching production call sites.
- **Windows Store alias double-filter**: Filtering happens both in `WhichCommandFinder` (path regex, L104–118) and `isValidPythonExecutable` (spawn-based, L263–269), providing defense in depth.
- **`DEBUG_PYTHON_DISCOVERY=true`** env var gates all verbose/diagnostic logging, keeping CI output clean by default.
- **`Logger` interface** (L11–14): Kept file-local to avoid coupling; `debug` is optional to support loggers without debug level.
