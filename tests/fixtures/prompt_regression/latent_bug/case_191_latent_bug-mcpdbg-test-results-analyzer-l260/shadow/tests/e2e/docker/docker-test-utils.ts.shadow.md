# tests\e2e\docker\docker-test-utils.ts
@source-hash: 72de2053702536e4
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:46Z

## Docker Test Utilities (`tests/e2e/docker/docker-test-utils.ts`)

Helper module providing all infrastructure needed to run MCP debugger end-to-end tests against a live Docker container. Used by e2e test suites to abstract Docker lifecycle management and MCP client setup.

### Module-Level Constants (L14–L20)
- `execAsync` (L14): Promisified `child_process.exec`
- `__filename` / `__dirname` (L16–17): ESM-compatible path resolution
- `ROOT` (L18): Resolved project root (3 levels up from this file)
- `DEFAULT_IMAGE` (L19): `process.env.DOCKER_IMAGE_NAME` or `'mcp-debugger:local'`
- `dockerBuildPromise` (L20): Module-level singleton promise to deduplicate concurrent build calls

---

### Interface: `DockerTestConfig` (L22–28)
Configuration bag for Docker test operations. All fields optional:
- `imageName`: Docker image tag (default: `DEFAULT_IMAGE`)
- `containerName`: Container name (default: `mcp-debugger-test-${Date.now()}`)
- `workspaceMount`: Host path to mount at `/workspace` (default: `ROOT/examples`)
- `logLevel`: MCP server log level (default: `'info'`)
- `forceRebuild`: Skip build cache and always run `docker build`

---

### `buildDockerImage(config?)` (L34–77) — exported
Ensures the Docker image exists and is current before tests run. Implements a **singleton promise pattern** (`dockerBuildPromise`) so concurrent calls do not trigger duplicate builds.

- If `forceRebuild` is true (from config or `DOCKER_FORCE_REBUILD=true` env), bypasses the singleton and calls `runDockerBuild` directly (L39–43).
- Otherwise, creates/reuses `dockerBuildPromise` which invokes `scripts/docker-build-if-needed.js` via `execAsync` (L50–59).
- `maxBuffer` is set to 64 MB (L54) to accommodate large Docker build output.
- On error: resets `dockerBuildPromise = null` (L61) so future calls retry; surfaces stdout/stderr from the exec error object.

---

### `runDockerBuild(imageName)` (L79–89) — internal
Directly runs `docker build -t <imageName> .` from `ROOT`. Logs stderr as warnings. Throws on failure. Called only by `buildDockerImage` when `forceRebuild` is set.

---

### `cleanupContainer(containerName)` (L94–110) — exported
Stops (`docker stop`) then removes (`docker rm`) a named container. Both operations are independently try/caught so a non-running or non-existent container does not throw.

---

### `createDockerMcpClient(config?)` (L115–197) — exported
Primary factory: creates a fully connected MCP `Client` over a `StdioClientTransport` backed by `docker run`.

**Docker run arguments (L132–152):**
- `--rm -i`: auto-remove, interactive (stdin)
- `--user <uid>:<gid>`: added only on non-Windows, non-CI Unix environments where `process.getuid`/`getgid` are available (L140–142)
- `-v <workspaceMount>:/workspace:rw`: mounts host examples dir
- `-v <ROOT>/logs:/tmp:rw`: maps host logs dir to container `/tmp`
- Container command: `stdio --log-level <logLevel> --log-file /tmp/docker-test.log`

**Returned object:**
```ts
{ client: Client, transport: StdioClientTransport, cleanup: () => Promise<void> }
```

`cleanup()` (L179–194): closes client, closes transport (both errors suppressed), then calls `cleanupContainer` as a safety net (container should already be removed via `--rm`).

On connection failure: calls `cleanupContainer` before re-throwing (L175).

---

### `hostToContainerPath(hostPath, workspaceMount?)` (L208–246) — exported
Pure path-conversion utility. Converts a host absolute or relative path to the path expected inside the container (relative to `/workspace`).

**Resolution priority:**
1. Already relative (no leading `/` and no `:`) → returned as-is (L213–215)
2. Starts with `workspaceMount + '/'` → strips prefix (L218–221)
3. Starts with resolved `ROOT/examples` dir → strips examples dir prefix (L224–230)
4. Starts with `ROOT` and sub-path begins `/examples/` → strips `/examples/` (L233–241)
5. Fallback: `path.basename(normalizedPath)` (L244–245)

Note: backslashes are normalized to forward slashes before all comparisons (L210).

---

### `getDockerLogs(containerName)` (L251–258) — exported
Returns last 100 lines of `docker logs <containerName>`. Returns empty string on failure (non-throwing).

---

### Architectural Patterns
- **Singleton build guard**: `dockerBuildPromise` (L20) prevents multiple parallel Docker builds within the same test process.
- **ESM compatibility**: Uses `fileURLToPath(import.meta.url)` pattern for `__dirname` equivalent (L16–17).
- **Graceful cleanup**: All container teardown operations are independently guarded with try/catch.
- **CI awareness**: `--user` flag logic (L140) avoids UID mapping in CI environments where it could cause permission issues.