# tests\e2e\docker\docker-entrypoint.test.ts
@source-hash: 18113ac79ba05773
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:27Z

## Docker Entrypoint Regression Test

End-to-end test suite that validates Docker entrypoint argument passing correctness. Specifically targets a historical quoting bug where `printf`-generated `entry.sh` emitted literal `\"` characters around `$@`, corrupting CLI argument passing to the container (e.g., `--version"` with trailing quote, `\"sse\"` mismatched as a subcommand).

### Environment Controls
- **`SKIP_DOCKER`** (L19): Gates the entire suite via `SKIP_DOCKER_TESTS=true` env var; uses `describe.skipIf` (L22).
- **`IMAGE_NAME`** (L20): Target Docker image, defaults to `mcp-debugger:local`, overridable via `DOCKER_IMAGE_NAME`.

### Suite Setup
- **`beforeAll`** (L23–25): Calls `buildDockerImage({ imageName: IMAGE_NAME })` with a 240-second timeout to build the Docker image before any test runs.

### Test Cases

#### `should pass --version without argument corruption` (L27–41)
Runs `docker run --rm <image> --version` (30s timeout, 60s test timeout). Asserts:
- Output does NOT contain `'unknown option'` or `'error:'`
- Output matches `/\d+\.\d+/` (semver-like version string)

#### `should pass sse --help without argument corruption` (L43–57)
Runs `docker run --rm <image> sse --help` (30s timeout, 60s test timeout). Asserts:
- Output does NOT contain `'unknown option'`
- Output contains `'-p'` (SSE `--port` option)
- Output contains `'sse'`

#### `should start SSE mode with -p argument` (L59–93)
Creates a named container `mcp-entrypoint-test-<timestamp>` and:
1. Starts container detached: `docker run -d --name <name> -p 0:3001 <image> sse -p 3001`
2. Waits 3 seconds for startup
3. Inspects running state via `docker inspect --format="{{.State.Running}}" <name>`; expects `'true'`
4. Checks container logs for absence of `'unknown option'` and `"error: unknown option '-p'"`
5. `finally` block: stops and removes the container (errors silently swallowed)

All three tests share a 60-second per-test timeout.

### Dependencies
- **`buildDockerImage`** from `./docker-test-utils.js` (L15): handles Docker build orchestration
- **`execAsync`** (L17): `util.promisify(child_process.exec)` — all Docker CLI interactions go through this
- **Vitest** test framework (L12): `describe`, `it`, `expect`, `beforeAll`