# scripts\test-docker-local.sh
@source-hash: 0632f5c61d428e70
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:49Z

## Docker Smoke Test Runner Script (`scripts/test-docker-local.sh`)

### Purpose
Bash script that orchestrates local execution of Docker-based smoke tests for the `mcp-debugger` project. Verifies containerized debugging functionality for both Python and JavaScript test suites.

### Execution Flow

1. **Environment setup** (L6, L14-17): Enables `set -e` (exit on error), defines ANSI color codes (`RED`, `GREEN`, `YELLOW`, `NC`).
2. **Directory resolution** (L20-23): Resolves script's own directory and project root via `BASH_SOURCE[0]`, then `cd`s to root.
3. **Docker availability check** (L27-31): Runs `docker info` silently; exits with code 1 if Docker daemon is not running.
4. **Project build** (L36): Runs `npm run build` to compile TypeScript before testing.
5. **Docker image build** (L42): Builds image tagged `mcp-debugger:test` from project root `Dockerfile`.
6. **Container cleanup** (L48): Removes any existing containers whose names contain `mcp-debugger-test` using `docker ps -a | grep | awk | xargs`.
7. **Test execution** (L62, L69): Runs Python and JavaScript smoke tests independently via `npx vitest run`, capturing exit codes in `PYTHON_RESULT` and `JS_RESULT`.
8. **Results summary and exit logic** (L78-108):
   - Python PASS + JS FAIL → exit 0 (known regression, expected state)
   - Both PASS → exit 0 (regression fixed)
   - Python FAIL (any) → exit 1 (unexpected, investigate)

### Key Variables
| Variable | Line | Description |
|---|---|---|
| `RED`, `GREEN`, `YELLOW`, `NC` | L14-17 | ANSI escape codes for colored terminal output |
| `SCRIPT_DIR` | L20 | Absolute path to this script's directory |
| `ROOT_DIR` | L21 | Absolute path to project root |
| `PYTHON_RESULT` | L61 | Exit code of Python Docker test run |
| `JS_RESULT` | L68 | Exit code of JavaScript Docker test run |

### Test Files Invoked
- `tests/e2e/docker/docker-smoke-python.test.ts` (L62)
- `tests/e2e/docker/docker-smoke-javascript.test.ts` (L69)

### Exit Code Semantics
- `0`: Python passes (JS failure is tolerated as a known regression)
- `1`: Docker not running (L29), OR Python tests fail or both fail unexpectedly (L108)

### Notable Design Decisions
- JavaScript test failure is explicitly tolerated (exit 0) at L96-102, with guidance to fix the JavaScript Docker adapter. A comment at L94 acknowledges this: "JavaScript may FAIL due to a known regression."
- `|| true` on the cleanup command (L48) prevents script termination if no matching containers exist.
- The `--reporter=verbose` flag (L62, L69) ensures detailed per-test output in both runs.
- Both test suites use `|| RESULT=$?` pattern to prevent `set -e` from aborting on test failure, allowing independent capture of each suite's result.