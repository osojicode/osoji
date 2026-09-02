# PR #643 hunk inventory — summary

Diff: `git diff -M --unified=0 14610d61..06d48fc4`, excluding `tests/**/__snapshots__/**` (24 files, 36 hunks), `changelog.d/*`, `scripts/check-docs.mjs`, `package.json`.

Denominator: **835 hunks** across **66 files**, grouped into **442 rows** (adjacent/same-claim hunks merged; `hunk_count`/`hunk_seqs`/`old_starts` record the merge).

Files: `pr643-hunk-inventory.jsonl` (one row per claim group) and this summary.


## Counts per partition

| partition | hunks | rows |
|---|---:|---:|
| correction | 277 | 153 |
| addition | 282 | 175 |
| restructure | 261 | 100 |
| deletion | 14 | 13 |
| generated | 1 | 1 |
| **total** | **835** | **442** |

## Counts per domain (corrections + deletions of false text)

| domain | hunks | rows |
|---|---:|---:|
| checkout | 280 | 156 |
| world | 4 | 4 |
| runtime | 3 | 3 |

Deletions that count as corrections (false text removed, checkout-verified): 6 rows (6 hunks) — included above and listed below with `[deletion]`.

Deletions of unverifiable text (runtime figures / act CLI flags; domain world|runtime, not proven false): 4 rows — counted in the world/runtime rows above.

Deletions of stale-but-not-false text (no domain): 3 rows.

## Checkout corrections by kind (rows)

| kind | rows |
|---|---:|
| false_statement | 50 |
| nonexistent_artifact | 28 |
| wrong_signature | 20 |
| omission_from_list | 14 |
| stale_pointer | 11 |
| wrong_path | 10 |
| wrong_count | 7 |
| stale_version | 7 |
| inverted_semantics | 5 |
| wrong_command | 4 |

## Classification rules applied

- Partition is decided from the diff text, per hunk group; the PR body was only a hint list.
- `domain` follows "what does the truth depend on", not the example list: Docker base-image tags (`Dockerfile` FROM lines), vitest pool settings (`vitest.config.ts`) and script names (`package.json`) are in-tree, so those rows are `checkout`. Only claims about ecosystem facts (Delve release history, npm registry state, debugger pause semantics) are `world`; unmeasured performance figures are `runtime`.
- Capability/behaviour claims whose enumeration omits a member the code supports (e.g. "Supported by Python, Go, Rust, .NET, Java, JavaScript" without C/C++) are `correction` with `kind=omission_from_list`. Inventory/tree lists that were merely incomplete (package lists, test-file lists) are `addition` with a note — split noted so an adjudicator can move them.
- `npm run X` -> `pnpm run X` is `restructure` unless the command could not work (`npm ci` with no package-lock; `-w` workspace flags noted). Version bump 0.24.2 -> 0.25.0 never appears as a correction.
- `use_mcp_tool(...)` -> `tool { json }` notation rewrites are `restructure` (64 hunks in 7 rows across docs/dotnet/README.md, docs/go/README.md, docs/java/README.md, docs/multiple-mcp-servers.md, docs/python/README.md, examples/README.md).
- Archive headers on the four renamed docs are `addition`; the falsified artefacts of the archived bodies are recorded in `notes` (negative greps at 14610d61).
- `.github/workflows/ci.yml` (1 hunk) is check-docs wiring: tagged `generated` as an exclude-miss (same class as the excluded package.json script).
- Ambiguous-but-not-false phrasing that was clarified (e.g. JS_SCOPE_KINDS export note, `MCP_WORKSPACE_ROOT` "default") is `restructure` with a note.

## Distinct `checkout` corrections (one line each; `[deletion]` = false text removed)

- `AGENTS.md` @-16 (x1) [false_statement]: Old: "`pnpm lint` applies the workspace-wide ESLint config; add `:fix` to auto-format when safe" — implies lint:fix covers what lint covers; lint:fix is only `eslint src/**/*.ts --fix` (packages/ and scripts/ are not auto-fixed).  
  evidence: package.json (scripts.lint = eslint "src/**/*.ts" "packages/*/src/**/*.ts" "scripts/**/*.{js,mjs,cjs}"; scripts["lint:fix"] = eslint src/**/*.ts --fix)
- `AGENTS.md` @-32 (x1) [false_statement]: Old: `--no-verify` "bypasses ALL pre-commit hooks including linting and tests" — the pre-commit hook runs no lint and no tests (personal-paths check, staged build-artifact/.tgz guards, optional docstar); lint/tests run on pre-push.  
  evidence: .husky/pre-commit (no lint/test invocation); .husky/pre-push (lint, typecheck:all, build, test:unit+test:integration)
- `ARCHITECTURE.md` @-7 (x1) [wrong_count]: Old: "pnpm workspaces with 13 packages (the root workspace plus 12 under `packages/`)" — packages/ holds 17 directories.  
  evidence: git ls-tree 14610d61 packages/ (17 entries: 9 adapter-*, codelldb-common, 5 codelldb-<platform>, mcp-debugger, shared)
- `ARCHITECTURE.md` @-31 (x1) [omission_from_list]: Old: "MCP Protocol (JSON-RPC over STDIO or SSE)" — omits the Streamable HTTP transport (the recommended one) and does not note SSE is deprecated.  
  evidence: src/cli/setup.ts:66 (sse "DEPRECATED: use http"), :79-80 (http "recommended")
- `ARCHITECTURE.md` @-55 (x1) [wrong_path]: Old: "MCP Server (`src/server.ts`): Registers 28 MCP tools, handles STDIO and SSE transports" and "Adapter Policies (`src/proxy/`)" — tool registration lives in src/server/ (tool-schemas.ts, tool-dispatch.ts, handlers/index.ts), transports are set up in src/cli/, and the policies live in packages/shared/src/interfaces/adapter-policy-*.ts, not src/proxy/.  
  evidence: src/server/tool-dispatch.ts:22 registerToolHandlers; src/server/handlers/index.ts TOOL_HANDLERS; packages/shared/src/interfaces/adapter-policy-map.ts; src/cli/setup.ts
- `CONTRIBUTING.md` @-127 (x1) [nonexistent_artifact]: Old: "We use ESLint and Prettier to maintain consistent code style" — there is no Prettier configuration or dependency in the repo.  
  evidence: package.json (no prettier dependency or format script); no .prettierrc in the tree; eslint.config.js only
- `CONTRIBUTING.md` @-154 (x2) [nonexistent_artifact]: Old VS Code advice "Format on save using Prettier" with "editor.formatOnSave": true — no Prettier in the repo.  
  evidence: package.json (no prettier); eslint.config.js
- `CONTRIBUTING.md` @-189 (x1) [nonexistent_artifact]: Old example "npx vitest run tests/unit/session/session-manager.test.ts" — tests/unit/session/ does not exist; SessionManager specs live under tests/core/unit/session/.  
  evidence: git ls-tree 14610d61 tests/unit/ (no session/); tests/core/unit/session/session-manager-state.test.ts
- `CONTRIBUTING.md` @-325 (x1) [false_statement]: Old tree comment "core/ # Core unit and integration tests" — tests/core/ contains only unit/.  
  evidence: git ls-tree 14610d61 tests/core/ (unit/ only)
- `README.md` @-61 (x1) [omission_from_list]: Old remote-attach list "(Python via debugpy, Ruby via rdbg, Java via JDWP)" omits JavaScript, whose host/port attach exists; and "direct-connect attach needs no local toolchain" is attached to a list that includes Java, which is spawn-mode.  
  evidence: packages/adapter-javascript/src/javascript-debug-adapter.ts:661 transformAttachConfig; packages/adapter-javascript/src/javascript-adapter-factory.ts:45 attach:"spawn"; packages/adapter-java/src/java-adapter-factory.ts:54 attach:"spawn"; python/ruby factories attach:"direct-connect"
- `README.md` @-163 (x1) [wrong_command]: Old docker command "docker run -v $(pwd):/workspace debugmcp/mcp-debugger:latest" has neither -i nor --rm; without -i stdin is closed before any client traffic, which stdio-command.ts treats as a detached container and keeps alive, so the MCP client never connects and the container leaks.  
  evidence: src/cli/stdio-command.ts (onStdinGone: MCP_CONTAINER && !sawClientTraffic -> stay alive); .mcp.json.example (docker run -i --rm)
- `README.md` @-296 (x4) [wrong_path]: Worked example passes the relative path "buggy_swap.py" as file/scriptPath; host mode rejects non-absolute paths ("Path must be absolute"), so the example fails on the first call.  
  evidence: src/utils/simple-file-checker.ts:46-53 (host mode rejects non-absolute paths); src/utils/container-path-utils.ts:70-72 (host mode passes path through unchanged)
- `docs/ACT_LOCAL_CI_TESTING.md` @-84 (x2) [stale_version]: Old act matrix examples use "--matrix node-version:20.x"; the CI matrix is node-version [22.x].  
  evidence: .github/workflows/ci.yml:26 (node-version: [22.x]); .nvmrc (22)
- `docs/ACT_LOCAL_CI_TESTING.md` @-247 (x1) [false_statement]: Old: "The CI runs `npm run test:ci-no-python` which excludes Python integration tests" — the build-and-test job runs pnpm run test:ci-coverage (unit + integration); test:ci-no-python is the release workflow.  
  evidence: .github/workflows/ci.yml:97 (pnpm run test:ci-coverage); .github/workflows/release.yml:94 (pnpm run test:ci-no-python)
- `docs/ACT_LOCAL_CI_TESTING.md` @-276 (x1) [wrong_command]: Old checklist "Dependencies installed: `npm ci`" — there is no package-lock.json; the workspace uses pnpm (workspace:* protocol), so npm ci cannot install it.  
  evidence: git ls-tree 14610d61 (pnpm-lock.yaml, pnpm-workspace.yaml, .pnpmrc; no package-lock.json)
- `docs/agent-debugging-guide.md` @-189 (x1) [false_statement]: Old: "CodeLLDB debug adapter is vendored via the `build:adapter` script ..., not during `pnpm install`" — the root postinstall hook runs `pnpm run vendor:adapters`, so it is vendored during install.  
  evidence: package.json scripts.postinstall = "pnpm run vendor:adapters"; scripts["vendor:adapters"] = pnpm run -r --if-present build:adapter
- `docs/agent-debugging-guide.md` @-256 (x2) [false_statement]: Old: "Use `dapLaunchArgs` to pass `mainClass` and `classpath`" with an example passing mainClass — the Java adapter derives mainClass from `program` and overwrites any supplied value.  
  evidence: packages/adapter-java/src/java-debug-adapter.ts:286-292
- `docs/agent-debugging-guide.md` @-306 (x1) [omission_from_list]: Old: "fully functional for Python, Ruby, JavaScript, Rust, Go, Java, and .NET/C#" omits C/C++, a shipped adapter.  
  evidence: packages/adapter-cpp/ (git ls-tree 14610d61 packages/); CHANGELOG.md:86-93 (0.24.0 C/C++ debugging support)
- `docs/agent-debugging-guide.md` @-312 (x1) [false_statement]: Old Java insight: "pass `mainClass`/`classpath` via `dapLaunchArgs`" — mainClass is derived from program/scriptPath, not passed.  
  evidence: packages/adapter-java/src/java-debug-adapter.ts:286-292
- `docs/architecture/README.md` @-93 (x2) [inverted_semantics]: Old launch sequence diagram: "SM->>Adapter: validateEnvironment()" then "PM->>Adapter: buildAdapterCommand()" — inverted: the session-side ProxyLauncher calls resolveExecutablePath()/buildAdapterCommand() and hands the adapter over via AdapterLease.transferTo(); ProxyManager is what calls validateEnvironment().  
  evidence: src/session/launch/proxy-launcher.ts:105 (AdapterLease.acquire), :117 (lease.transferTo), :412 (adapter.resolveExecutablePath), :470 (adapter.buildAdapterCommand); src/proxy/proxy-manager.ts:718 (this.adapter.validateEnvironment)
- `docs/architecture/README.md` @-126 (x1) [wrong_signature]: ProxyManager constructor listing omitted the `options?: ProxyManagerOptions` parameter.  
  evidence: src/proxy/proxy-manager.ts:270-276 (constructor(..., options: ProxyManagerOptions = {}))
- `docs/architecture/README.md` @-131 (x1) [nonexistent_artifact]: Old comment: "adapter.prepareSpawnContext() sets up environment/args" — no adapter method of that name exists; prepareSpawnContext is ProxyManager's own private method.  
  evidence: src/proxy/proxy-manager.ts:703 (private async prepareSpawnContext); no prepareSpawnContext in packages/shared/src (git grep)
- `docs/architecture/README.md` @-266 (x1) [stale_version]: Old version history: "**Unreleased** - C/C++ adapter, 9 adapters total" — the C/C++ adapter shipped in v0.24.0 (project is at 0.24.2).  
  evidence: CHANGELOG.md:86 ([0.24.0] - 2026-08-19) and :93 (C/C++ debugging support); package.json version 0.24.2
- `docs/architecture/README.md` @-278 (x1) [stale_pointer]: Old footer links "[refactoring-summary.md](./refactoring-summary.md)" — no such file in docs/architecture/ (it is in docs/archive/architecture/).  
  evidence: git ls-tree 14610d61 docs/architecture/ (no refactoring-summary.md); docs/archive/architecture/refactoring-summary.md
- `docs/architecture/adapter-api-reference.md` @-256 (x1) [wrong_signature]: Old: "`listAvailableAdapters(): Promise<AdapterMetadata[]>`" — the method returns AdapterManifestEntry[].  
  evidence: packages/shared/src/interfaces/adapter-registry.ts:66; src/adapters/adapter-registry.ts:296
- `docs/architecture/adapter-development-guide.md` @-21 (x1) [stale_version]: Old prerequisite: "TypeScript 5.9+" — the root devDependency is typescript ^6.0.2.  
  evidence: package.json:195 ("typescript": "^6.0.2")
- `docs/architecture/api-reference.md` @-293 (x2) [wrong_signature]: Old: "`createSession(params: CreateSessionParams): Promise<SessionInfo>`" — SessionManager.createSession takes an inline object and returns DebugSessionInfo (whose id field is `id`); no SessionInfo type exists.  
  evidence: src/session/session-manager-core.ts:217 (createSession(params: {language; name?; executablePath?}): Promise<DebugSessionInfo>); packages/shared/src/models/index.ts:386-392
- `docs/architecture/api-reference.md` @-305 (x4) [nonexistent_artifact]: Old: "`startDebugging(params: StartDebuggingParams): Promise<DebugResult>`" with an object of {sessionId, script, launchConfig, executablePath, args, env, cwd} — no StartDebuggingParams type exists; startDebugging is positional (sessionId, scriptPath, scriptArgs?, dapLaunchArgs?, dryRunSpawn?, adapterLaunchConfig?, breakOnExceptions?).  
  evidence: src/session/session-manager-operations.ts:184-192; git grep StartDebuggingParams 14610d61 -- src packages (no matches)
- `docs/architecture/api-reference.md` @-330 (x4) [wrong_signature]: Old: "`continue(sessionId, threadId?)`", "`stepOver/stepInto/stepOut(sessionId, threadId?): Promise<void>`" — none of these take a threadId; continue returns DebugResult and the step methods return DebugResult<StepResultData>.  
  evidence: src/session/session-manager-operations.ts:302-320 (stepOver/stepInto/stepOut(sessionId): Promise<DebugResult<StepResultData>>; continue(sessionId): Promise<DebugResult>)
- `docs/architecture/api-reference.md` @-342 (x2) [nonexistent_artifact]: Old: "`terminate(sessionId: string): Promise<void>` Terminates the debug session." — no terminate() method exists on the SessionManager.  
  evidence: git grep "terminate(" 14610d61 -- src/session (no method); src/session/session-manager-core.ts:272 closeSession
- `docs/architecture/api-reference.md` @-354 (x1) [wrong_signature]: Old: "`getVariables(sessionId, variablesReference): Promise<Variable[]>`" omits the optional names filter.  
  evidence: src/session/session-manager-data.ts:107 (getVariables(sessionId, variablesReference, names?))
- `docs/architecture/api-reference.md` @-362 (x1) [nonexistent_artifact]: Old: "`attachToProcess(sessionId, attachConfig: AttachConfig)`" — no AttachConfig type exists; the parameter is an inline object (port/host/processId/timeout/sourcePaths/stopOnEntry/justMyCode/verifyTimeout/breakOnExceptions/adapterConfig) and the result is DebugResult<AttachResultData>.  
  evidence: src/session/session-manager-operations.ts:350-368; git grep "\bAttachConfig\b" 14610d61 -- src packages/shared/src (no such type)
- `docs/architecture/api-reference.md` @-380 (x1) [wrong_signature]: Old: "`getLocalVariables(sessionId, includeSpecial?): Promise<LocalVariablesResult>` ... by traversing all stack frames" — no LocalVariablesResult type exists (inline return object), the method also takes names?, and it stops at the first frame yielding usable locals.  
  evidence: src/session/session-manager-data.ts:272-330 (getLocalVariables(sessionId, includeSpecial, names?), inline return type, stop at first usable frame)
- `docs/architecture/api-reference.md` @-402 (x1) [wrong_signature]: Old ProxyManager constructor "(adapter, launcher, fileSystem, logger, runtimeEnv?)" omits the options?: ProxyManagerOptions parameter.  
  evidence: src/proxy/proxy-manager.ts:270-276
- `docs/architecture/api-reference.md` @-425 (x1) [omission_from_list]: Old ProxyManager event list omits breakpoints-synced.  
  evidence: src/proxy/proxy-manager.ts:77
- `docs/architecture/api-reference.md` @-466 (x1) [wrong_signature]: Old: "`listAvailableAdapters(): Promise<AdapterMetadata[]>`" — returns AdapterManifestEntry[].  
  evidence: src/adapters/adapter-registry.ts:296; packages/shared/src/interfaces/adapter-registry.ts:66
- `docs/architecture/api-reference.md` @-600 (x3) [wrong_signature]: Usage example calls "sessionManager.startDebugging({ sessionId, script, launchConfig })" (object form) and reads the id as `sessionInfo.sessionId` — startDebugging is positional and DebugSessionInfo's id field is `id`.  
  evidence: src/session/session-manager-operations.ts:184-192; packages/shared/src/models/index.ts:387 (id: string)
- `docs/architecture/api-reference.md` @-611 (x1) [false_statement]: Old: "SessionManager is not an EventEmitter" — SessionManagerCore extends EventEmitter.  
  evidence: src/session/session-manager-core.ts:156 (export abstract class SessionManagerCore extends EventEmitter)
- `docs/architecture/component-design.md` @-13 (x1) [wrong_count]: Old: SessionManagerOperations facade "(~350 lines)" — the file is 403 lines.  
  evidence: src/session/session-manager-operations.ts (wc -l = 403)
- `docs/architecture/component-design.md` @-43 (x1) [wrong_signature]: Old constructor list "AttachController(ctx, proxyLauncher, breakpoints)" omits the pauseCoordinator parameter (and the ExecutionController/ExpressionEvaluator/RedefineClassesController constructors).  
  evidence: src/session/attach/attach-controller.ts:29-33 (4 params incl. pauseCoordinator); src/session/execution/execution-controller.ts:117-119; src/session/inspection/expression-evaluator.ts:61-63
- `docs/architecture/component-design.md` @-95 (x1) [wrong_signature]: Old API listing: "setBreakpoint(sessionId, file, line, condition?)" and startDebugging without breakOnExceptions, step methods returning DebugResult — actual setBreakpoint takes a bp object and returns {breakpoint, warning}; startDebugging has a 7th breakOnExceptions param; step methods return DebugResult<StepResultData>.  
  evidence: src/session/session-manager-operations.ts:184-192 (startDebugging), :215-231 (setBreakpoint(sessionId, bp)), :302-312 (stepOver/Into/Out -> DebugResult<StepResultData>)
- `docs/architecture/component-design.md` @-101 (x1) [wrong_signature]: Old: "pause(sessionId: string): Promise<DebugResult>" — pause takes an optional threadId and returns DebugResult<PauseResultData>.  
  evidence: src/session/session-manager-operations.ts:325
- `docs/architecture/component-design.md` @-103 (x1) [wrong_signature]: Old attachToProcess config type omits breakOnExceptions and adapterConfig and the AttachResultData return type.  
  evidence: src/session/session-manager-operations.ts:350-368
- `docs/architecture/component-design.md` @-314 (x1) [stale_pointer]: Old comment: "proxyLogPathFor is the single home for this name (src/proxy/proxy-log-path.ts)" — no such file; it lives in src/proxy/session-log-layout.ts.  
  evidence: git ls-tree 14610d61 src/proxy/ (session-log-layout.ts; no proxy-log-path.ts)
- `docs/architecture/javascript-adapter.md` @-34 (x1) [omission_from_list]: Old: "`pnpm -w run build:adapters:all` ... will build mock, python, and javascript adapters" — the script also builds the ruby adapter.  
  evidence: package.json scripts["build:adapters:all"] (mock, python, ruby, javascript)
- `docs/architecture/system-overview.md` @-59 (x1) [omission_from_list]: Old: "CLI entry point with subcommands (stdio, http, sse [deprecated], check-rust-binary)" omits the doctor subcommand.  
  evidence: src/cli/setup.ts:93 (.command("doctor"))
- `docs/architecture/system-overview.md` @-210 (x1) [stale_version]: Old: "TypeScript 5.x with strict mode" — the devDependency is typescript ^6.0.2.  
  evidence: package.json:195
- `docs/architecture/system-overview.md` @-212 (x1) [stale_version]: Old: "Debug Adapter Protocol (DAP) 1.51.0" — the repo depends on @vscode/debugprotocol ^1.68.0 and pins no spec revision.  
  evidence: package.json:155 ("@vscode/debugprotocol": "^1.68.0")
- `docs/architecture/system-overview.md` @-258 (x1) [false_statement]: Old: "`mcp-debugger-launcher` package provides easy installation" — the PyPI package is debug-mcp-server-launcher with a debug-mcp-server entry point.  
  evidence: mcp_debugger_launcher/pyproject.toml:2 (name = "debug-mcp-server-launcher"), :33
- `docs/architecture/testing-architecture.md` @-19 (x3) [false_statement]: Old isolation strategy: the suite "runs with maxWorkers: 1, fileParallelism: false, testTimeout: 30000" and "serial execution is slower but eliminates ... non-deterministic failures" stated suite-wide — the unit project (the majority) runs fileParallelism: true with a 15 s timeout; only the integration and e2e projects are serial.  
  evidence: vitest.config.ts (projects: unit -> pool forks, fileParallelism: true, testTimeout: 15000; serialPool {fileParallelism: false, maxWorkers: 1, testTimeout: 30000} for integration/e2e)
- `docs/architecture/testing-architecture.md` @-72 (x2) [wrong_count]: Old: "The project maintains two parallel mock systems" (mocks and fakes) — a third kind, compile-checked fakes under tests/test-utils/fakes/, exists.  
  evidence: tests/test-utils/fakes/fake-debug-adapter.ts (git ls-tree 14610d61)
- `docs/architecture/testing-architecture.md` @-112 (x1) [nonexistent_artifact]: Old: "`MockLogger` (simple vi.fn() stubs ...)" — there is no MockLogger class; the helper is createMockLogger().  
  evidence: tests/test-utils/mocks/mock-logger.ts:12 (export function createMockLogger); no "class MockLogger" in tests/test-utils
- `docs/architecture/testing-architecture.md` @-152 (x1) [wrong_count]: Old: "Twenty-one per-language STDIO smoke tests: ..." — the enumerated list omits mcp-server-smoke-dotnet-attach.test.ts (and the glob also contains restart, http-stale-reap and SSE files), so the count is stale.  
  evidence: git ls-tree 14610d61 tests/e2e/ (26 mcp-server-smoke-*.test.ts files incl. mcp-server-smoke-dotnet-attach.test.ts)
- `docs/architecture/testing-architecture.md` @-169 (x1) [wrong_count]: Old: "Tests all 25 MCP tools across 9 languages" — the test derives its list from TOOL_NAMES, which has 28 entries.  
  evidence: tests/e2e/comprehensive-mcp-tools.test.ts:17,86 (ALL_TOOLS = [...TOOL_NAMES]); src/server/tool-schemas.ts:28-57 (28 names)
- `docs/architecture/testing-architecture.md` @-173 (x1) [wrong_count]: Old: "tests/e2e/docker/ (4 test files: Python, JavaScript, Rust smoke tests + entrypoint validation)" — the directory has 7 test files.  
  evidence: git ls-tree 14610d61 tests/e2e/docker/ (docker-entrypoint, docker-smoke-cpp-attach, docker-smoke-cpp, docker-smoke-javascript, docker-smoke-python, docker-smoke-ruby-attach, docker-smoke-rust)
- `docs/architecture/testing-architecture.md` @-184 (x1) [wrong_count]: Old: "tests/e2e/npx/ (2 test files: Python and JavaScript smoke tests)" — there are 3 (Rust too).  
  evidence: git ls-tree 14610d61 tests/e2e/npx/ (npx-smoke-javascript, npx-smoke-python, npx-smoke-rust)
- `docs/architecture/testing-architecture.md` @-208 (x1) [false_statement]: Old: "All event simulation uses `process.nextTick()` or `setTimeout()` to defer emission" — MockProxyManager's simulateStopped/simulateExited/simulateError/simulateExit emit synchronously.  
  evidence: tests/test-utils/mocks/mock-proxy-manager.ts:234-250 (simulate* methods call this.emit directly; nextTick used only at :59, :87, :173, :179)
- `docs/commit-workflow.md` @-4 (x6) [false_statement]: Old: the pre-commit workflow lets you "skip time-consuming tests"; `git commit` "Runs all checks: ... 🐌 Tests and builds (can be slow)"; --skip-tests skips "build verification, tests" — the pre-commit hook runs no tests and no build (personal-paths check, build-artifact and .tgz guards, optional docstar).  
  evidence: .husky/pre-commit (no test/build invocation); scripts/safe-commit.sh
- `docs/commit-workflow.md` @-57 (x2) [false_statement]: Old pre-push description "ESLint, Build verification, Full test suite" / "Pre-push hooks will still run all tests" — pre-push runs lint, the baseline guard, typecheck:all, a clean build, then test:unit + test:integration (not the full suite; e2e runs in CI).  
  evidence: .husky/pre-push (pnpm run lint; typecheck:all; npm run clean && npm run build; npm run test:unit && npm run test:integration)
- `docs/development/build-pipeline.md` @-30 (x1) [false_statement]: Under "Scripts That Require Fresh Builds ... include `npm run build`": old lists "`test`: Full test suite (unit + integration)" and "`test:integration`" — `test` runs all three projects (incl. e2e) and `test:integration` is a bare `vitest run --project integration` with no build.  
  evidence: package.json scripts (test = pnpm run build && pnpm run pretest:docker && vitest run; "test:integration" = vitest run --project integration, no pretest:integration); vitest.config.ts projects
- `docs/development/build-pipeline.md` @-59 (x3) [inverted_semantics]: Old: "Host mode: Absolute paths are allowed; Container mode: Absolute paths are rejected with an error", "The E2E container test now correctly expects path rejection errors", "absolute paths are rejected in container mode" — inverted: host mode rejects non-absolute paths; container mode rejects nothing and re-roots every path under MCP_WORKSPACE_ROOT.  
  evidence: src/utils/simple-file-checker.ts:46-53 (host-mode "Path must be absolute"); src/utils/container-path-utils.ts:69-88 (container mode re-roots, no rejection)
- `docs/development/build-pipeline.md` @-94 (x2) [false_statement]: Old: bundling "Enables distribution in minimal Alpine containers" / "Uses minimal Alpine runtime with only Node.js" — the runtime stage is ubuntu:26.04 (builder node:26-slim), not Alpine.  
  evidence: Dockerfile:6 (FROM node:26-slim ... AS builder), :169 (FROM ubuntu:26.04), :211 (COPY --from=builder /usr/local/bin/node)
- `docs/development/dap-sequence-reference.md` @-125 (x1) [false_statement]: Old: handleStatusMessage emits "[code ?? 1, ...]" while the dap-core path emits "[code || 1, ...]" folding exit code 0 to 1, and both paths emit — both now emit [code ?? null, signal, expected] and the functional-core emit is suppressed once exitEmitted latches.  
  evidence: src/proxy/proxy-manager.ts:1448 (message.code ?? null), :1187-1188 (exit suppressed when exitEmitted); src/dap-core/handlers.ts:132 (message.code ?? null)
- `docs/development/debugging-guide.md` @-231 (x5) [false_statement]: Old log guidance pointed only at logs/ ("Watch log directory", "Tail all logs: tail -f logs/*.log") — per-session proxy/adapter logs live in a separate tree under <tmpdir>/debug-mcp-server/sessions/<sessionId>/run-<startedAt>/, so logs/ alone misses them.  
  evidence: src/session/session-manager-core.ts:197 (logDirBase default os.tmpdir()/debug-mcp-server/sessions); src/proxy/session-log-layout.ts
- `docs/development/debugging-guide.md` @-291 (x1) [nonexistent_artifact]: Old: "DEBUG=* npm test -- tests/unit/proxy/proxy-manager.test.ts" — no such file; the proxy-manager tests are split into proxy-manager.start / .handshake / .branch-coverage / -message-handling.  
  evidence: git ls-tree 14610d61 tests/unit/proxy/ (proxy-manager.start.test.ts, proxy-manager.handshake.test.ts, proxy-manager.branch-coverage.test.ts, proxy-manager-message-handling.test.ts; no proxy-manager.test.ts)
- `docs/development/debugging-guide.md` @-294 (x1) [nonexistent_artifact]: Old: "vitest run tests/unit/session/session-manager.test.ts" — tests/unit/session/ does not exist.  
  evidence: git ls-tree 14610d61 tests/unit/ (no session/); tests/core/unit/session/session-manager-state.test.ts
- `docs/development/debugging-guide.md` @-360 (x2) [nonexistent_artifact]: Old: "extend the `registerTools()` method in `src/server.ts` ... add a case in the CallToolRequestSchema handler's switch" — no registerTools() exists and server.ts has no tool request handlers; tools are named in TOOL_NAMES, advertised in buildToolDefinitions() (src/server/tool-schemas.ts) and handled via TOOL_HANDLERS (src/server/handlers/index.ts).  
  evidence: git grep registerTools 14610d61 -- src packages (no matches); src/server/tool-schemas.ts:28 TOOL_NAMES; src/server/handlers/index.ts TOOL_HANDLERS; src/server/tool-dispatch.ts:22 registerToolHandlers
- `docs/development/git-hooks-guide.md` @-25 (x3) [false_statement]: Old pre-push: "Runs the full test suite (`npm test`)" / "Tests run here, push only if tests pass" / "Run tests locally: npm test" — the hook runs lint, the baseline guard, typecheck:all, a clean build, then test:unit + test:integration, not npm test / the full suite.  
  evidence: .husky/pre-push (pnpm run lint; typecheck:all; npm run clean && npm run build; npm run test:unit && npm run test:integration)
- `docs/development/setup-guide.md` @-51 (x2) [wrong_path]: Old clone/issue URLs "github.com/your-username/debug-mcp-server" — the repository is github.com/debugmcp/mcp-debugger.  
  evidence: package.json:9 (repository url git+https://github.com/debugmcp/mcp-debugger.git), :140 (bugs url)
- `docs/development/setup-guide.md` @-133 (x1) [false_statement]: Old comment on `npm run dev`: "Development build (watch mode)" — the script is `ts-node-esm src/index.ts`, a one-shot run, not a watch-mode build.  
  evidence: package.json scripts.dev = ts-node-esm src/index.ts
- `docs/development/setup-guide.md` @-291 (x3) [false_statement]: Old: "Create a `.env` file for development" listing DEBUG_MCP_LOG_LEVEL / PYTHON_PATH / TEST_TIMEOUT — nothing in the repo loads a .env file (no dotenv dependency), so the file is ignored.  
  evidence: package.json (no dotenv); git grep dotenv 14610d61 -- src scripts vitest.config.ts (no matches)
- `docs/development/testing-guide.md` @-31 (x1) [nonexistent_artifact]: Old: "npm test -- tests/unit/session/session-manager.test.ts" (no such file — tests/unit/session/ does not exist) and "npm test -- --grep 'ProxyManager'" (Vitest has no --grep flag; use -t).  
  evidence: git ls-tree 14610d61 tests/unit/ (no session/); tests/core/unit/session/session-manager-workflow.test.ts
- `docs/development/testing-guide.md` @-53 (x1) [false_statement]: Old: "No hard thresholds are enforced in the config; the project aims for 90%+ coverage by convention" — vitest.config.ts enforces thresholds (statements 90, branches 80).  
  evidence: vitest.config.ts (coverage.thresholds: { statements: 90, branches: 80 })
- `docs/development/testing-guide.md` @-288 (x3) [wrong_signature]: Old example called "sessionManager.setBreakpoint(session.id, 'test-script.py', 10)" (positional) and "sessionManager.startDebugging({ sessionId, script })" (object form) — startDebugging is positional and setBreakpoint takes a breakpoint object.  
  evidence: src/session/session-manager-operations.ts:184-192 (startDebugging(sessionId, scriptPath, scriptArgs?, ...)), :215-231 (setBreakpoint(sessionId, bp))
- `docs/development/testing-guide.md` @-324 (x1) [wrong_signature]: Old transcription of createMockFileSystem omitted the readTail member the real helper has.  
  evidence: tests/test-utils/helpers/test-dependencies.ts (createMockFileSystem includes readTail)
- `docs/development/testing-guide.md` @-353 (x1) [nonexistent_artifact]: Old fixtures tree: "javascript-e2e/ # JavaScript/TypeScript fixtures (simple.js, async.js, worker.js, app.ts)" — the directory holds only app.ts and tsconfig.json; the tree also lacked adversarial-adapter/.  
  evidence: git ls-tree 14610d61 tests/fixtures/ (javascript-e2e: app.ts, tsconfig.json; adversarial-adapter/server.mjs)
- `docs/development/testing-guide.md` @-392 (x2) [nonexistent_artifact]: Old "VS Code Debugging: ... Press F5 or use 'Debug Tests' launch configuration" — the repository ships no .vscode/launch.json, so no such configuration exists.  
  evidence: git ls-tree 14610d61 (no .vscode directory)
- `docs/development/testing-guide.md` @-399 (x2) [false_statement]: Old "Console Logging" example told you to console.log inside tests — vitest.config.ts installs an onConsoleLog filter that suppresses stdout by default, so those lines never appear.  
  evidence: vitest.config.ts (function onConsoleLog: noise patterns; default `return type === "stderr"`)
- `docs/development/testing-guide.md` @-414 (x3) [nonexistent_artifact]: Old "Vitest UI Mode: npm run test:ui ... opens a browser" — no test:ui script exists.  
  evidence: package.json scripts (no "test:ui"; no @vitest/ui dependency)
- `docs/diagnostics.md` @-53 (x2) [inverted_semantics]: Old Delve lookup: "`GOBIN` is searched first, then `GOPATH/bin`, then PATH" — inverted: after an explicit path (executablePath, else DLV_PATH via the policy) the adapter searches PATH first and only then GOPATH/bin (GOBIN preferred), and DLV_PATH was undocumented.  
  evidence: packages/adapter-go/src/utils/go-utils.ts:63-98 (findDelveExecutable: preferredPath, then findInPath, then getGopathBin); packages/shared/src/interfaces/adapter-policy-go.ts:123-130 (DLV_PATH)
- `docs/diagnostics.md` @-166 (x1) [false_statement]: Old: "Per-session proxy log: each session writes `proxy-<sessionId>.log` to the OS temp directory, at the same level as the server log" and "Server log: logs/debug-mcp-server-<pid>.log (working-directory-relative)" — proxy logs go to <tmpdir>/debug-mcp-server/sessions/<sessionId>/run-<startedAt>/, and the default server log path is module-relative (<module-dir>/../../logs), with cwd only as a fallback.  
  evidence: src/session/session-manager-core.ts:197; src/proxy/session-log-layout.ts; src/utils/logger.ts:176-188
- `docs/docker-support.md` @-61 (x7) [omission_from_list]: The example autoApprove list named 21 of the 28 tools, omitting list_breakpoints, remove_breakpoint, clear_breakpoints, restart_debugging, expose_session, unexpose_session and get_output.  
  evidence: src/server/tool-schemas.ts:28-57 (TOOL_NAMES, 28 entries) vs docs/docker-support.md:55-85 at 14610d61 (21 tool names)
- `docs/docker-support.md` @-93 (x1) [nonexistent_artifact]: Old example path "examples/test.py" — no such file; examples/python/fibonacci.py exists.  
  evidence: git ls-tree 14610d61 examples/ (no test.py); examples/python/fibonacci.py
- `docs/docker-support.md` @-98 (x2) [omission_from_list]: Old: "The image vendors linux-x64 CodeLLDB" / prebuilt binaries "must be Linux-compiled (linux-x64)" — the Dockerfile selects linux-x64 or linux-arm64 from TARGETARCH, so the arm64 image vendors arm64 CodeLLDB.  
  evidence: Dockerfile:82-84 (ARG TARGETARCH; case arm64 -> CODELLDB_ARCH=linux-arm64, else linux-x64)
- `docs/docker-support.md` @-204 (x1) [stale_version]: Old Dockerfile summary: "Uses Node.js 22-slim for building" and "Uses Ubuntu 24.04 for runtime" — the builder is node:26-slim and the runtime stage is ubuntu:26.04.  
  evidence: Dockerfile:6 (FROM node:26-slim@sha256:... AS builder), :169 (FROM ubuntu:26.04@sha256:...)
- `docs/error-handling-guide.md` @-76 (x1) [wrong_path]: Old: "The MCP server (`src/server.ts`) throws McpError directly for invalid parameters ... typed session-lifecycle errors are caught in each session-scoped tool handler" in src/server.ts — server.ts holds no request handlers; rejection happens in src/server/tool-dispatch.ts and the classification lives in shared helpers in src/server/tool-result.ts with handlers under src/server/handlers/.  
  evidence: src/server/tool-dispatch.ts:22 registerToolHandlers; src/server/tool-result.ts:44-83 (isTypedSessionError, sessionErrorToResult, sessionErrorResultOrThrow, rethrowAsMcpError); src/server.ts (no setRequestHandler for tools)
- `docs/error-handling-guide.md` @-89 (x2) [nonexistent_artifact]: Worked example showed a per-tool instanceof catch chain inside the server ("// Server (catches typed session errors per-tool)") that does not exist; replaced with the real continueExecutionTool handler using sessionErrorToResult().  
  evidence: src/server/handlers/execution-tools.ts (continueExecutionTool); src/server/tool-result.ts:56 sessionErrorToResult
- `docs/getting-started.md` @-42 (x4) [wrong_path]: Old prompts "Set a breakpoint in examples/python/fibonacci.py at line 21" and "Start debugging examples/python/fibonacci.py" use repository-relative paths, which host mode rejects; the walkthrough now uses an absolute path and targets the bug on line 46.  
  evidence: src/utils/simple-file-checker.ts:46-53; examples/python/fibonacci.py:46 (buggy_value line)
- `docs/getting-started.md` @-90 (x1) [false_statement]: Old: "Logs are only written when a `--log-file` path is specified" — the logger always attaches a file transport, defaulting to <module-dir>/../../logs/debug-mcp-server-<pid>.log (or /app/logs/debug-mcp-server.log in a container).  
  evidence: src/utils/logger.ts:176-197 (projectRootDefaultLogPath), :197 (options.file || default), :216-219 (file transport always created)
- `docs/go/README.md` @-255 (x1) [false_statement]: Old: "The MCP tools do not expose goroutine-specific commands (listing goroutines, switching between goroutines ...)" — goroutines surface as DAP threads: list_threads lists them and get_stack_trace takes a threadId.  
  evidence: src/server/tool-schemas.ts:48 (list_threads) and :205 (get_stack_trace threadId); src/session/session-manager-data.ts:181 (getStackTrace(sessionId, threadId?)); packages/adapter-go/src/go-debug-adapter.ts:348 (hideSystemGoroutines = true)
- `docs/go/README.md` @-301 (x1) [wrong_path]: Old workflow step: start debugging with "program: ./myprogram" — a relative path, which host mode rejects ("Path must be absolute").  
  evidence: src/utils/simple-file-checker.ts:46-53
- `docs/java/README.md` @-53 (x1) [false_statement]: Old: the adapter "transparently forwards `classpath`, `sourcePath`, `cwd`, `env`, and `args`" — the JDI bridge's launch handler never reads cwd, env or sourcePath (it reads mainClass, classpath, stopOnEntry, javaPath, vmArgs, args), so listing them as forwarded launch settings implies an effect they do not have.  
  evidence: packages/adapter-java/java/JdiDapServer.java:355-394 (launch handler reads mainClass/classpath/stopOnEntry/javaPath/vmArgs/args only); packages/adapter-java/src/java-debug-adapter.ts:302-313 (adapter does copy sourcePath/cwd/env into the config)
- `docs/java/README.md` @-55 (x3) [false_statement]: Old: "`mainClass` (required): Fully qualified class name" (examples pass mainClass) and "`stopOnEntry` ... (default: `true`)" — mainClass is derived from `program` and overwritten, and through start_debugging the session layer merges stopOnEntry:false beneath dapLaunchArgs, so the effective default is false; the workflow step also used a relative classpath ".".  
  evidence: packages/adapter-java/src/java-debug-adapter.ts:286-292 (mainClass derived), :283 (?? true adapter fallback); src/session/session-manager-core.ts:197-200 (defaultDapLaunchArgs stopOnEntry:false)
- `docs/java/README.md` @-92 (x3) [nonexistent_artifact]: Old attach docs: "`sourcePaths`: Directories containing `.java` source files for source mapping" (examples pass sourcePaths) — the JDI bridge's attach handler reads only host/hostName, port and stopOnEntry; there is no source-path list.  
  evidence: packages/adapter-java/java/JdiDapServer.java:326-342 (attach handler: host/hostName, port, stopOnEntry)
- `docs/javascript/README.md` @-222 (x1) [false_statement]: Old limitation: "Remote debugging requires manual configuration" — remote attach is a supported host/port attach handled by the adapter.  
  evidence: packages/adapter-javascript/src/javascript-debug-adapter.ts:661 transformAttachConfig; packages/adapter-javascript/src/javascript-adapter-factory.ts:45 attach:"spawn"
- `docs/javascript/README.md` @-232 (x1) [wrong_path]: Old: "See `/examples/javascript/`" — a filesystem-root path; the directory is examples/javascript/ relative to the repo root.  
  evidence: git ls-tree 14610d61 examples/ (examples/javascript exists; no /examples at filesystem root)
- `docs/jit-diagnostics/README.md` @-64 (x1) [false_statement]: Old: "The python adapter has no path-mapping option" — the adapter forwards debugpy pathMappings through adapterConfig.  
  evidence: packages/adapter-python/src/python-debug-adapter.ts:77 (pathMappings type), :95 (passthrough key), :500-515
- `docs/logging-format-specification.md` @-5 (x1) [false_statement]: Old: "other log files may exist alongside these (e.g., proxy process logs ...)" — per-session proxy/adapter logs live in their own tree under <sessionLogBase>/<sessionId>/run-<startedAt>/ (default os.tmpdir()/debug-mcp-server/sessions), not alongside the server log.  
  evidence: src/proxy/session-log-layout.ts (sessionRunDirectoryFor, proxyLogPathFor); src/session/session-manager-core.ts:197 (logDirBase default)
- `docs/multiple-mcp-servers.md` @-53 (x5) [nonexistent_artifact]: Old: "test each server individually using the provided test scripts: `.\test-server.cmd` ... `.\test-github-mcp.cmd`" — neither script exists in the repository.  
  evidence: git grep -l test-server.cmd 14610d61 (only docs/multiple-mcp-servers.md and docs/windows-launcher-guide.md); root tree has no test-server.cmd / test-github-mcp.cmd
- `docs/patterns/dependency-injection.md` @-321 (x1) [nonexistent_artifact]: Old: "**Location**: `tests/unit/proxy/proxy-manager-lifecycle.test.ts`" — no such file; the ProxyManager suite is proxy-manager.start/.handshake/-message-handling/.branch-coverage.  
  evidence: git ls-tree 14610d61 tests/unit/proxy/ (no proxy-manager-lifecycle.test.ts)
- `docs/patterns/error-handling.md` @-127 (x9) [stale_pointer]: Old: "**Example**: SessionManager error handling (`src/session/session-manager-operations.ts`)" with a 5-parameter startDebugging body doing its own teardown (`this._getSessionById`, `this._updateSessionState`, `proxyManager.stop()`) — startDebugging in the facade is a one-line delegate; the body and its error handling live in DebugLauncher (7 params) and the teardown is failProxySetup() in proxy-failure-diagnostics.ts.  
  evidence: src/session/session-manager-operations.ts:184-200 (delegate); src/session/launch/debug-launcher.ts:110 (startDebugging); src/session/launch/proxy-failure-diagnostics.ts:251 (failProxySetup)
- `docs/patterns/error-handling.md` @-182 (x2) [stale_pointer]: Old: "`SessionManagerOperations` validates it (positive, finite, clamped to 600000)" — the validation is the free function resolveDapTimeoutOverride() in src/session/dap-request-helpers.ts (MAX_DAP_TIMEOUT_MS), used by the collaborators.  
  evidence: src/session/dap-request-helpers.ts:15 (MAX_DAP_TIMEOUT_MS), :35 (resolveDapTimeoutOverride), :59 (withTimeoutHint)
- `docs/patterns/error-handling.md` @-202 (x4) [stale_pointer]: Old: "**Example**: SessionManager step operation grace window (`src/session/session-manager-operations.ts`)" with `session.proxyManager?.once('stopped', ...)` — the step body lives in ExecutionController (execution-controller.ts), is table-driven over STEP_KINDS, reads stepGraceMs via ctx.tunables and registers stopped/terminated/exited/exit listeners with on() behind a settle() guard.  
  evidence: src/session/execution/execution-controller.ts:65 (STEP_KINDS), :239/:305 (settle), :303-313 (ctx.tunables.stepGraceMs)
- `docs/patterns/error-handling.md` @-231 (x5) [stale_pointer]: Old: "**Example**: SessionManager attach verification window (`src/session/session-manager-operations.ts`)" — the polling is verifyAttachThreads() in src/session/attach/attach-verification.ts, driven by AttachController.  
  evidence: src/session/attach/attach-verification.ts:39 (verifyAttachThreads); src/session/attach/attach-controller.ts
- `docs/patterns/error-handling.md` @-262 (x2) [false_statement]: Old: "An open bag ... type DebugResultData = ProxyFailureDiagnostics & { ... [key: string]: unknown; }" — DebugResultData is a closed interface (extends ProxyFailureDiagnostics) with no index signature.  
  evidence: src/session/session-manager-core.ts:60-92 (export interface DebugResultData extends ProxyFailureDiagnostics, named optional fields only)
- `docs/patterns/error-handling.md` @-286 (x1) [wrong_signature]: Old: "`AttachResultData` (`attachConfig`)" as an alias adding a field — AttachResultData is a plain alias of DebugResultData; StepResultData/PauseResultData also carry a required message.  
  evidence: src/session/session-manager-core.ts:96-114 (StepResultData, PauseResultData, AttachResultData = DebugResultData)
- `docs/patterns/event-management.md` @-22 (x2) [false_statement]: Removes a transcribed ProxyManagerEvents interface that had drifted: it lacked output, breakpoint, adapter-capabilities, function-breakpoints-synced and breakpoints-synced, and showed 'exited' with no exitCode and 'exit' without the expected flag.  
  evidence: src/proxy/proxy-manager.ts:48-77 (ProxyManagerEvents: exited(exitCode?), output, breakpoint, exit(code, signal?, expected?), breakpoints-synced ...)
- `docs/patterns/event-management.md` @-68 (x3) [wrong_signature]: Old code excerpts declare sessionEventHandlers / setupProxyEventHandlers / cleanupProxyEventHandlers as `private` — they are `protected` in SessionManagerCore.  
  evidence: src/session/session-manager-core.ts:171, :428, :1314
- `docs/patterns/event-management.md` @-237 (x1) [false_statement]: Old handleDapEvent excerpt: "this.emit('exited')" dropping the exit code — the real code forwards exitedBody?.exitCode (and also emits output/breakpoint events).  
  evidence: src/proxy/proxy-manager.ts:1318 (this.emit('exited', exitCode)); :52-55 (event signatures)
- `docs/patterns/event-management.md` @-301 (x1) [false_statement]: Old init-exit excerpt: "if (this.isDryRun && code === 0) { resolve(); } else { reject(...) }" — the initialization exit handler rejects unconditionally; a clean dry run is acknowledged by the dry_run_complete status (#596).  
  evidence: src/proxy/proxy-manager.ts:441-450 (handleExit during initialization: unconditional reject with stderr tail); :1034-1035 (isDryRun check only affects log level on process exit)
- `docs/patterns/event-management.md` @-314 (x3) [stale_pointer]: Old: step-wait "**Location**: `src/session/session-manager-operations.ts`" with proxyManager.once('stopped') — it lives in ExecutionController and registers five settle-guarded on() listeners.  
  evidence: src/session/execution/execution-controller.ts:239-313
- `docs/patterns/event-management.md` @-343 (x6) [stale_pointer]: Old: launch readiness wait "**Location**: `src/session/session-manager-operations.ts`" with a post-listener state check that also treats PAUSED as ready — it is waitForLaunchReadiness() in src/session/launch/launch-readiness.ts, which consults policy.isSessionReady and checks only STOPPED/ERROR before registering listeners.  
  evidence: src/session/launch/launch-readiness.ts:32 (waitForLaunchReadiness), :62-63 (policy.isSessionReady), :106 (STOPPED || ERROR pre-check)
- `docs/patterns/event-management.md` @-407 (x7) [nonexistent_artifact]: Old: "**Location**: `tests/unit/proxy/proxy-manager-lifecycle.test.ts`" with an example built on fakeLauncher.prepareProxy/simulateExit — no such file; the suite is proxy-manager.start/.handshake/-message-handling/.branch-coverage and the excerpt now mirrors proxy-manager-message-handling.test.ts.  
  evidence: git ls-tree 14610d61 tests/unit/proxy/ (no proxy-manager-lifecycle.test.ts); tests/unit/proxy/proxy-manager-message-handling.test.ts:60, :414; tests/unit/test-utils/test-proxy-manager.ts
- `docs/quickstart.md` @-70 (x1) [false_statement]: Old comment on the buggy line "# Bug: dividing by wrong value" — the shown line `total / len(numbers) + 1` divides correctly and adds 1.  
  evidence: docs/quickstart.md:70-71 at 14610d61 (the example script itself)
- `docs/quickstart.md` @-97 (x2) [wrong_path]: Worked example calls set_breakpoint with "file": "buggy_math.py" and start_debugging with "scriptPath": "buggy_math.py" — relative paths, which host mode rejects ("Path must be absolute").  
  evidence: src/utils/simple-file-checker.ts:46-53
- `docs/rust-adapter-performance.md` @-53 (x1) [wrong_command]: Old recommendation: build with "`cargo +stable-gnu build --target x86_64-pc-windows-gnu`" — a --target build lands in target/x86_64-pc-windows-gnu/debug/, which the adapter never looks in (it resolves only target/{debug,release}/<name>), so a .rs scriptPath would not find the binary.  
  evidence: packages/adapter-rust/src/rust-debug-adapter.ts:738-742, :780-781 (path.join(projectRoot, "target", release ? "release" : "debug", ...))
- `docs/stack-trace-filtering.md` @-11 (x1) [omission_from_list]: Old language list omitted Rust and C/C++, which both filter via filterLldbStackFrames, while presenting Python as the only unfiltered language.  
  evidence: packages/shared/src/interfaces/adapter-policy-rust.ts:70 and adapter-policy-cpp.ts:58 (filterStackFrames: filterLldbStackFrames); lldb-policy-shared.ts:267
- `docs/stack-trace-filtering.md` @-64 (x2) [false_statement]: Old: Go "No fallback when every frame is internal — the result may be empty" and "Go and .NET have no such fallback and may return an empty array" — FrameAnchorResolver keeps the top frame and sets allFramesInternal for every language (#346), so the filtered stack is never empty.  
  evidence: src/session/inspection/frame-anchor-resolver.ts:119-125 (allFramesInternal = true; frames = [frames[0]]); src/server/handlers/inspection-tools.ts:84
- `docs/stack-trace-filtering.md` @-66 (x1) [stale_pointer]: Old: "4. **SessionManagerData** (`src/session/session-manager-data.ts`) — Applies filtering" — filtering is applied by FrameAnchorResolver (src/session/inspection/frame-anchor-resolver.ts), reached from SessionManagerData.  
  evidence: src/session/inspection/frame-anchor-resolver.ts:119-138 (filtering + hiddenFrameCount); src/session/session-manager-data.ts:181 getStackTrace
- `docs/tool-reference.md` @-144 (x3) [inverted_semantics]: Old: set_breakpoint / get_source_context "`file` ... (absolute or relative to project root)" and "The response includes the absolute path even if you provide a relative path" — host mode rejects a relative path ("Path must be absolute"); only container mode re-roots paths.  
  evidence: src/utils/simple-file-checker.ts:46-53; src/utils/container-path-utils.ts:69-88
- `docs/tool-reference.md` @-241 (x1) [omission_from_list]: Logpoint support table row "Python, JavaScript/TypeScript, Go, Rust, mock" omits C/C++.  
  evidence: packages/shared/src/interfaces/adapter-policy-cpp.ts:37 (supportsLogPoints: true)
- `docs/tool-reference.md` @-353 (x3) [wrong_path]: Sample responses/requests use relative paths ("Debugging started for examples/python_simple_swap/swap_vars.py", "file": "test_script.py") that host mode would reject.  
  evidence: src/utils/simple-file-checker.ts:46-53
- `docs/tool-reference.md` @-466 (x1) [wrong_signature]: Old continue_execution sample response included "state": "running" — the handler returns only success and message.  
  evidence: src/server/handlers/execution-tools.ts:98 (jsonResult({ success, message }))
- `docs/tool-reference.md` @-483 (x4) [false_statement]: Old pause_execution: "returns immediately; the paused state is updated asynchronously" and the state "is still `running`" at answer time — the tool waits up to the pause grace window (~5s) for the stop and answers `paused` when it lands; `running` + pending only when it does not.  
  evidence: src/session/execution/execution-controller.ts:487 (timeoutMs: pauseGraceMs), :542-548 (pending path, ErrorMessages.pausePending); src/utils/error-messages.ts:110
- `docs/tool-reference.md` @-676 (x2) [false_statement]: Old: get_local_variables "traverses all stack frames and their scopes ... collects scopes and variables across all frames (not just the top frame)" — it walks down from the top frame and stops at the first frame that yields usable locals.  
  evidence: src/session/session-manager-data.ts:272-330 (getLocalVariables: "Stop as soon as a frame yields usable locals"; frameAnchorResolver.resolve)
- `docs/troubleshooting.md` @-101 (x6) [inverted_semantics]: Old: "File paths are resolved relative to your MCP client's working directory" with per-client resolution rules ("If VS Code is open in C:\projects\myapp, then test.py resolves to ...") and a sample error ("Resolved path: ...\Microsoft VS Code\test.py ... Note: Relative paths are resolved from: ...") — host mode performs no resolution and rejects non-absolute paths ("Path must be absolute"); container mode re-roots under MCP_WORKSPACE_ROOT; the real message is "<label> not found: ... Looked for: ... Error: Path must be absolute".  
  evidence: src/utils/simple-file-checker.ts:46-55; src/utils/container-path-utils.ts:69-88; src/server.ts:686 (not-found message format)
- `docs/usage.md` @-125 (x4) [wrong_path]: Worked example passes the relative path "swap_vars.py" as file/scriptPath (and echoes it in messages); host mode rejects relative paths.  
  evidence: src/utils/simple-file-checker.ts:46-53
- `docs/usage.md` @-304 (x1) [wrong_signature]: Old evaluate_expression sample response included "message": "Evaluated expression: a == b" — no such field is produced.  
  evidence: git grep "Evaluated expression" 14610d61 -- src (no matches); src/server/handlers/inspection-tools.ts:155 (jsonResult(result) from ExpressionEvaluator)
- `docs/usage.md` @-320 (x1) [wrong_signature]: Old continue_execution sample response included "state": "running" — the handler returns only success and message.  
  evidence: src/server/handlers/execution-tools.ts:98
- `docs/usage.md` @-387 (x1) [omission_from_list]: Old: breakpoint removal "(by id, or file+line)" omits removal by function name, which remove_breakpoint supports.  
  evidence: src/server/tool-schemas.ts:139 (remove_breakpoint `function` property)
- `docs/validation-script.md` @-3 (x1) [false_statement]: Old: "Validates your changes in a clean clone to simulate exactly what CI will see" — the script does not run lint or typecheck:all, which CI gates on.  
  evidence: scripts/validate-push.js (install/build/test only); .github/workflows/ci.yml:190-263 (lint job)
- `docs/vitest-llm-config.md` @-13 (x1) [false_statement]: Old: "Console filtering and reporter settings are applied via npm scripts and utility wrappers rather than directly in the config file" — onConsoleLog and reporters are defined in vitest.config.ts.  
  evidence: vitest.config.ts (function onConsoleLog; reporters: process.env.CI ? [dot, json] : [default]; sharedProjectTest spreads onConsoleLog into every project)
- `docs/vitest-llm-optimization.md` @-100 (x1) [stale_pointer]: Old sample path "tests/integration/python_debug_workflow.test.ts" — the file lives at tests/adapters/python/integration/python_debug_workflow.test.ts.  
  evidence: git ls-tree 14610d61 tests/adapters/python/integration/python_debug_workflow.test.ts (exists); tests/integration/ has no such file
- `docs/vitest-llm-optimization.md` @-117 (x1) [nonexistent_artifact]: Old: "two independent TAP filtering implementations: scripts/llm-env.ps1 ... and scripts/llm-env.sh (Bash, for CI/Linux)" — there is no llm-env.sh.  
  evidence: git ls-tree 14610d61 scripts/ (llm-env.ps1 only)
- `examples/go/README.md` @-25 (x4) [nonexistent_artifact]: Old instructions invent CLI subcommands: "mcp-debugger create_debug_session --language go", "mcp-debugger set_breakpoint --file main.go --line 15", "mcp-debugger start_debugging --script ./hello_world" / "--script ./fibonacci.test" — the CLI has only stdio, sse, http, doctor and check-rust-binary; these are MCP tools.  
  evidence: src/cli/setup.ts:52-111 (commands: stdio, sse, http, doctor, check-rust-binary); src/index.ts (setup calls)
- `examples/go/README.md` @-113 (x1) [false_statement]: Old tip: "Use `hideSystemGoroutines: true` to filter runtime goroutines" — the adapter forces hideSystemGoroutines = true after merging the config, so the user setting has no effect.  
  evidence: packages/adapter-go/src/go-debug-adapter.ts:348 (goConfig.hideSystemGoroutines = true)
- `examples/go/README.md` @-124 (x1) [false_statement]: Old tip: "Use `showGlobalVariables: true` to inspect package-level variables" — the adapter forces showGlobalVariables = false, so the setting is overwritten.  
  evidence: packages/adapter-go/src/go-debug-adapter.ts:347 (goConfig.showGlobalVariables = false)
- `examples/rust/README.md` @-8 (x2) [false_statement]: Old: "The Rust adapter will automatically download CodeLLDB when you run: cd packages/codelldb-common; npm run build:adapter" — CodeLLDB is vendored by the root postinstall hook during pnpm install; the manual command is only a re-vendor.  
  evidence: package.json scripts.postinstall = pnpm run vendor:adapters (-> build:adapter in codelldb-common)
- `examples/rust/README.md` @-29 (x2) [nonexistent_artifact]: Old instructions invent CLI subcommands: "mcp-debugger create_debug_session --language rust", "mcp-debugger set_breakpoint --file src/main.rs --line 10", "mcp-debugger start_debugging --script target/debug/hello_world" — the CLI has only stdio, sse, http, doctor and check-rust-binary.  
  evidence: src/cli/setup.ts:52-111
- `examples/rust/README.md` @-60 (x2) [nonexistent_artifact]: Old: "Each project can include a `debug_config.json` for custom launch settings" with a sample file — nothing in the adapter or server reads such a file; launch settings are start_debugging arguments (args / dapLaunchArgs).  
  evidence: git grep debug_config 14610d61 -- src packages/*/src (no matches); packages/adapter-rust/src/rust-debug-adapter.ts transformLaunchConfig
- `packages/adapter-mock/README.md` @-38 (x1) [wrong_command]: Old: "--host flag ... (e.g., `--host=127.0.0.1`)" — the process parses `--host` as a separate argv token only; the `--host=` form is not parsed.  
  evidence: packages/adapter-mock/src/mock-adapter-process.ts:126 (case "--host": reads next argv)
- `packages/mcp-debugger/README.md` @-66 (x1) [false_statement]: Old: "direct-connect attach modes (Python `debugpy --listen`, Ruby `rdbg --open`, Java JDWP) need no local language toolchain" — Java attach is spawn-mode (local JDI bridge on the host JDK); only Python and Ruby are direct-connect.  
  evidence: packages/adapter-java/src/java-adapter-factory.ts:54 attach:"spawn"; packages/adapter-python/src/python-adapter-factory.ts:55 and packages/adapter-ruby/src/ruby-adapter-factory.ts:48 attach:"direct-connect"
- `packages/mcp-debugger/README.md` @-89 (x1) [false_statement]: Old: "Common options (all commands): --log-level" — doctor and check-rust-binary do not take --log-level; only stdio/sse/http do.  
  evidence: src/cli/setup.ts:52-111 (--log-level on stdio/sse/http only; doctor has --json/--timeout; check-rust-binary has --json)
- `scripts/validate-push.js` @-133 (x1) [nonexistent_artifact]: --smoke ran "pnpm test -- tests/unit/index.test.ts tests/core/unit/server/server.test.ts"; tests/core/unit/server/server.test.ts does not exist (deleted in the server split).  
  evidence: git ls-tree 14610d61 tests/core/unit/server/ (no server.test.ts; server-initialization.test.ts and server-lifecycle.test.ts exist)
- `scripts/validate-push.js` @-220 (x1) [false_statement]: Help text: "simulating exactly what CI will see" — the script runs install/build/tests only; CI additionally gates on lint and typecheck:all.  
  evidence: scripts/validate-push.js (steps 5-7: pnpm install, pnpm build, pnpm test); .github/workflows/ci.yml:190-263 (lint job: pnpm run lint, typecheck:all, check:all-personal-paths, changelog:check)
- `skills/debugging/SKILL.md` @-52 (x1) [omission_from_list]: Function breakpoints "Supported by Python/Go/Rust/.NET/Java/JavaScript" and logpoints "(Python/JS/Go/Rust; Java and .NET reject it)" both omit C/C++ (supports both), and the logpoint rejection list omits Ruby (supportsLogPoints: false).  
  evidence: packages/shared/src/interfaces/adapter-policy-cpp.ts:37-38; packages/shared/src/interfaces/adapter-policy-ruby.ts:13
- `skills/debugging/references/java.md` @-19 (x3) [false_statement]: Old: "`dapLaunchArgs.mainClass` is required" (and the example passes mainClass and cwd) and "For Java, `stopOnEntry` defaults to `true`" — the adapter derives mainClass from `program` and overwrites any supplied value, and through start_debugging the session layer merges stopOnEntry:false beneath the launch args, so the effective default is false.  
  evidence: packages/adapter-java/src/java-debug-adapter.ts:286-292 (mainClass set from program), :283 (config.stopOnEntry ?? true); src/session/session-manager-core.ts:197-200 (defaultDapLaunchArgs stopOnEntry:false)
- `src/server/tool-schemas.ts` @-116 (x1) [omission_from_list]: set_breakpoint `function` description: "Supported by Python, Go, Rust, .NET, Java, and JavaScript adapters" omits C/C++, whose policy declares supportsFunctionBreakpoints: true.  
  evidence: packages/shared/src/interfaces/adapter-policy-cpp.ts:38; packages/adapter-cpp/src/cpp-debug-adapter.ts:889
- `src/server/tool-schemas.ts` @-137 (x1) [omission_from_list]: set_breakpoint `logMessage` description: "Supported by the Python, JavaScript, Go, Rust, and mock adapters; not by Java, .NET, or Ruby" omits C/C++, whose policy declares supportsLogPoints: true.  
  evidence: packages/shared/src/interfaces/adapter-policy-cpp.ts:37; packages/adapter-cpp/src/cpp-debug-adapter.ts:923
- `tests/README.md` @-209 (x1) [false_statement]: Old vitest config summary: "Test timeout: 30 seconds", "Max workers: 1 (process-spawning tests require serial execution)", "File parallelism: Disabled" — the unit project (the bulk of the suite) runs fileParallelism: true with a 15 s timeout; only integration/e2e are serial. Include patterns also omitted src/** and packages/**/src/**.  
  evidence: vitest.config.ts (unit project: pool forks, fileParallelism: true, testTimeout: 15000; serialPool for integration/e2e; UNIT_INCLUDE)
- `CONTRIBUTING.md` @-137 (x1) [deletion] [nonexistent_artifact]: Removes "# Format code with Prettier (if configured) / npm run format" — no format script exists.  
  evidence: package.json scripts (no "format" entry)
- `docs/ACT_LOCAL_CI_TESTING.md` @-155 (x1) [deletion] [nonexistent_artifact]: Removes "act -j build-and-test --env-file .env.ci" and "act -j build-and-test --job build-and-test --rerun".  
  evidence: git ls-tree 14610d61 (no .env.ci in the tree)
- `docs/ACT_LOCAL_CI_TESTING.md` @-234 (x1) [deletion] [false_statement]: Removes "Prerequisites: Local Docker Image ... Act does not build local Docker images automatically; if mcp-debugger:local is not present, container-related jobs will fail" — the container-tests job builds the image itself.  
  evidence: .github/workflows/ci.yml container-tests job ("Build Docker image": docker build -t mcp-debugger:local .)
- `docs/architecture/adapter-api-reference.md` @-3 (x1) [deletion] [stale_version]: Removes "Status: Unreleased (post-v0.23.0 main)".  
  evidence: package.json version 0.24.2; CHANGELOG.md:76-86 (0.24.0-0.24.2 released)
- `docs/development/build-pipeline.md` @-35 (x1) [deletion] [false_statement]: Removes "`test:coverage:quiet`: Silent coverage run" from the list of scripts that build first — that script has no pre hook and no inline build.  
  evidence: package.json scripts["test:coverage:quiet"] = vitest run --coverage --reporter=dot --silent (no pretest:coverage:quiet)
- `docs/javascript/README.md` @-217 (x1) [deletion] [stale_pointer]: Removes a link to ./typescript-source-map-investigation.md, which does not exist under docs/javascript/ (it lives in docs/archive/).  
  evidence: git ls-tree 14610d61 docs/javascript/ (README.md, architecture-diagram.md only); docs/archive/typescript-source-map-investigation.md

## `world` / `runtime` corrections and false deletions

- `docs/go/README.md` @-10 (x1) [world]: Old prerequisite: "Delve 0.17.0+ installed with DAP support" — `dlv dap` did not exist until Delve 1.6.0.  
  note: Delve release history is an ecosystem fact. The checkout agrees with the OLD text: packages/adapter-go/src/go-adapter-factory.ts:53 declares minimumDebuggerVersion: "0.17.0", so this is not detectable by doc-vs-code comparison (the metadata carries the same stale figure).
- `docs/quickstart.md` @-13 (x1) [world]: Old heading "Option 1: Using npm (when published)" — the package is published (@debugmcp/mcp-debugger; CI canary installs the published package).  
  note: Registry state is world-domain; in-tree workflow/changelog only corroborate.
- `docs/quickstart.md` @-171 (x1) [world]: Old get_variables sample response listed "average": "31.0" while paused at line 6 — the breakpoint pauses before the assignment executes, so `average` does not exist yet.  
  note: Debugger pause-before-line semantics; not checkable from the checkout.
- `docs/ACT_LOCAL_CI_TESTING.md` @-193 (x1) [deletion] [world]: Removes the "Debugging Inside Container" block (act --container-options "-it" --exec sh).  
  note: Validity of the act --exec flag is an act-CLI fact; not verified.
- `docs/rust-adapter-performance.md` @-8 (x1) [deletion] [runtime]: Removes the "Operation Response Times" list (< 500ms session creation, < 200ms variable inspection, ...) — figures no in-tree harness produces.  
  note: Unverifiable latency claims; not falsified from the checkout (scripts/mem-bench.mjs measures RSS only).
- `docs/rust-adapter-performance.md` @-27 (x1) [deletion] [runtime]: Removes the Strengths / Current Limitations / Optimization Opportunities lists (runtime claims such as "respond within 1 second", planning checklists) in favour of the CodeLLDB pin.  
  note: Limitations that survive (system-stop, MSVC) are restated in hunk 10; the checklists were planning prose. Adds the CodeLLDB 1.11.8 pin (packages/codelldb-common/vendor-manifest.json:4).
- `docs/stack-trace-filtering.md` @-106 (x1) [deletion] [runtime]: Removes the "Testing: verified with the JavaScript smoke tests which all pass" note in favour of a Related link.  
  note: Stale test-status prose; not falsified from the checkout.

## Adjudication-sensitive rows and things not fully classified

- `docs/java/README.md` @-53: "transparently forwards classpath, sourcePath, cwd, env, args" — the adapter does forward those keys (java-debug-adapter.ts:302-313); the JDI bridge never reads cwd/env/sourcePath (JdiDapServer.java:355-394). Classified `correction` on the implied effect; an adjudicator may prefer `restructure` + bug #642.
- `docs/go/README.md` @-10: "Delve 0.17.0+" is `world` — and the checkout AGREES with the old text (go-adapter-factory.ts:53 `minimumDebuggerVersion: "0.17.0"`), so a doc-vs-code comparison cannot detect it.
- Omission-from-list corrections (14 rows: `ARCHITECTURE.md`@-31, `README.md`@-61, `docs/agent-debugging-guide.md`@-306, `docs/architecture/api-reference.md`@-425, `docs/architecture/javascript-adapter.md`@-34, `docs/architecture/system-overview.md`@-59, `docs/docker-support.md`@-61, `docs/docker-support.md`@-98, `docs/stack-trace-filtering.md`@-11, `docs/tool-reference.md`@-241, `docs/usage.md`@-387, `skills/debugging/SKILL.md`@-52, `src/server/tool-schemas.ts`@-116, `src/server/tool-schemas.ts`@-137) are corrections by the task's "wrong capability claim" rule. Inventory omissions were classified `addition` with a note saying the old list was incomplete — 8 rows (`AGENTS.md`@-5, `CONTRIBUTING.md`@-303, `docs/development/build-pipeline.md`@-15, `docs/development/git-hooks-guide.md`@-9, `docs/development/setup-guide.md`@-102, `packages/shared/README.md`@-56, `tests/README.md`@-97, `tests/e2e/README.md`@-14) that an adjudicator could move to `correction/omission_from_list`.
- Relative-path worked examples (README, quickstart, usage, getting-started, tool-reference, docs/go, docker-support example) are `correction/wrong_path` on the strength of simple-file-checker.ts host-mode rejection; each is a doc example rather than a prose claim.
- Minor corrections (line counts "~350 lines", `private` vs `protected`, missing `readTail` in a transcription, "/examples/javascript/" slash) are included and flagged "Minor" in notes; they are real doc-vs-code mismatches but low value.
- New-side claims added by the PR (e.g. env-var descriptions, KNOWN_ISSUES attach gaps, launcher docker command) were spot-checked where cheap, not exhaustively verified; the inventory classifies the OLD text.
- Not verified from the checkout: whether `act` accepts `--exec`/`--job`/`--rerun` (ACT doc deletions, `world`), Python 3.7 vs 3.8 debugpy floor, output-size figures in the vitest-llm docs (`runtime`).
