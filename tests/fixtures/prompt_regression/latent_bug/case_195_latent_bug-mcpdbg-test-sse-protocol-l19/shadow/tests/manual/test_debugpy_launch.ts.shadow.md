# tests\manual\test_debugpy_launch.ts
@source-hash: f3d9c27a877a3888
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:57Z

## Purpose

Manual test script that verifies `debugpy.adapter` can be spawned as a subprocess on Windows. Intended to be run manually during development to confirm that the Python debug adapter process launches correctly, emits output, and can be terminated cleanly.

---

## Key Symbols

### `testLaunch` (L6–89)
Async function that orchestrates the entire test. Steps:
1. **Hardcoded config** (L9–12): Windows Python path `C:\Python313\python.exe`, adapter host `127.0.0.1`, port `5678`, session ID `test-session`.
2. **Log dir setup** (L15–21): Creates `<tmpdir>/debugpy-adapter-test-session` via `fs.ensureDir`. Mirrors production `PythonDebugger` behavior.
3. **Spawn args** (L23–28): `-m debugpy.adapter --host 127.0.0.1 --port 5678 --log-dir <logPath>`.
4. **Process spawning** (L34–52): Calls `spawn()` with `stdio: ['ignore', 'pipe', 'pipe']` and `detached: false`. Guards against null/no-PID cases.
5. **Event listeners** (L56–74): Attaches `stdout`, `stderr`, `error`, `exit`, and `close` handlers — all logging to console.
6. **30-second wait** (L78): `setTimeout(30000)` keeps the script alive to observe adapter output.
7. **Cleanup** (L80–88): Sends `SIGTERM` to the adapter process if still alive after the wait.

### Module-level entry (L91)
`testLaunch().catch(...)` — top-level invocation with unhandled-rejection guard.

---

## Dependencies

| Import | Usage |
|--------|-------|
| `child_process.spawn`, `ChildProcess` | Spawning the debugpy.adapter process |
| `path` | Building the log directory path |
| `os` | `os.tmpdir()` for log directory base |
| `fs-extra` | `fs.ensureDir` to create log directory |

---

## Hardcoded Values / Environment Assumptions

- **Python path** (L9): `C:\Python313\python.exe` — Windows-only; must be manually updated per environment. Comment acknowledges this.
- **Port** (L11): `5678` — fixed, may conflict if already in use.
- **Session ID** (L12): `'test-session'` — dummy value only for constructing the log path.

---

## Architectural Notes

- This is a **manual smoke test**, not part of any automated test suite — there are no assertions, test framework imports, or pass/fail signals.
- The pattern (log dir → spawn → observe → kill) mirrors the production `PythonDebugger` adapter launch flow, making it useful for isolating environment/spawn issues from higher-level extension logic.
- The 30-second wait (L78) is intentional to allow inspection of process output in the terminal.
- `detached: false` (L37) ensures the child is tied to the test process lifecycle.