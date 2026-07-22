# src\proxy\proxy-bootstrap.js
@source-hash: 246ff3a7463ac517
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:19Z

## Purpose
Entry-point bootstrap script for the proxy child process. Runs before TypeScript is available (plain ESM JS). Handles orphan detection, environment setup, and dynamic loading of the actual proxy implementation (bundled or unbundled).

## Key Responsibilities

### Module-level Setup (L10-13)
- Reconstructs `__filename`/`__dirname` from `import.meta.url` (ESM compat, L10-11)
- Creates a timestamped log prefix `bootstrapLogPrefix` for all bootstrap output (L13)

### `logBootstrapActivity(message)` (L16-18)
- Internal helper: writes all bootstrap output to `stderr` via `console.error`. Intentional choice for proxy startup debugging (no TypeScript logging available yet).

### Orphan Detection Loop (L32-40)
- `setInterval` runs every 10 seconds (L32, 10000ms)
- Calls `shouldExitAsOrphanFromEnv(process.ppid, process.env)` to detect if the process has been orphaned (ppid=1 outside containers)
- If orphaned, sends `SIGTERM` to self (L38) — not `process.exit()` — so the worker's signal handler in `dap-proxy-core.ts`/`ProxyRunner` can perform async cleanup (auto-detach)
- **No SIGTERM/SIGINT/disconnect handlers registered here** (L20-24): worker module owns those to avoid race conditions with async cleanup

### Proxy Loading IIFE (L44-88)
1. Sets `process.env.DAP_PROXY_WORKER = 'true'` (L47) to signal proxy mode to downstream code
2. Resolves two candidate paths relative to `__dirname` (L51-52):
   - `proxy-bundle.cjs` — preferred bundled version
   - `dap-proxy-entry.js` — fallback unbundled entry
3. Prefers bundle when it exists via `fs.existsSync` (L55)
4. Exits with code 1 if chosen file doesn't exist (L61-64)
5. Constructs a `file://` URL for cross-platform ESM dynamic import (L69-72):
   - Unix: `file:///path` (leading `/` already present)
   - Windows: `file:///C:/path` (adds three slashes for drive letter paths)
6. Dynamically imports the proxy via `await import(proxyUrl)` (L76)
7. On any error: logs full stack trace and exits with code 1 (L83-87)

## Architecture Notes
- **No signal handlers** registered here intentionally — worker owns lifecycle (L20-24)
- **Bundle-first strategy**: prefers `proxy-bundle.cjs` for reliability, falls back to unbundled ESM
- **Windows path handling**: manual `file:///` URL construction to handle backslash paths (L69-72)
- All logging goes to stderr — this is intentional (L1-3 comment, L17)
- Orphan check avoids `process.exit()` directly to allow async worker cleanup (L34-35 comments)