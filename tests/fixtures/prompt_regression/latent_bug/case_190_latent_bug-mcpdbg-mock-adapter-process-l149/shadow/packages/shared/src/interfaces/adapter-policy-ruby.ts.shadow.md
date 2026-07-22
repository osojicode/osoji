# packages\shared\src\interfaces\adapter-policy-ruby.ts
@source-hash: 80f57405b3dc15c2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:26Z

## Ruby Adapter Policy (`adapter-policy-ruby.ts`)

### Purpose
Implements the `AdapterPolicy` interface for the Ruby `rdbg` (ruby/debug) DAP adapter. This is a concrete policy object configuring all adapter-specific behavior for Ruby debugging sessions.

---

### Primary Export

**`RubyAdapterPolicy`** (L7–211) — A singleton `AdapterPolicy` object literal. All methods are inline arrow functions. No class instantiation required.

---

### Key Methods & Behaviors

| Method | Lines | Behavior |
|---|---|---|
| `supportsReverseStartDebugging` | L9 | `false` — rdbg does not support reverse start |
| `childSessionStrategy` | L10 | `'none'` — no child sessions |
| `shouldDeferParentConfigDone` | L11 | Always returns `false` |
| `buildChildStartArgs` | L12–14 | Always throws — child sessions unsupported |
| `isChildReadyEvent` | L15–17 | Returns `true` when `evt.event === 'initialized'` |
| `extractLocalVariables` | L18–44 | Extracts variables from top stack frame's local scope; matches `presentationHint === 'locals'` OR `name === 'Local variables'` (rdbg-specific fallback) |
| `getLocalScopeName` | L45–47 | Returns `['Local variables']` (rdbg scope name) |
| `getDapAdapterConfiguration` | L48–52 | Returns `{ type: 'rdbg' }` |
| `resolveExecutablePath` | L53–59 | Returns provided path, else `RUBY_PATH`, `RUBY_EXECUTABLE`, or `'ruby'` |
| `getDebuggerConfiguration` | L60–66 | `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true` |
| `isSessionReady` | L67 | `state === SessionState.PAUSED` |
| `validateExecutable` | L68–87 | Spawns `rubyCmd --version`, resolves `true` only if exit code 0 AND has stdout/stderr output |
| `requiresCommandQueueing` | L88 | Always `false` |
| `shouldQueueCommand` | L89–95 | Returns `{ shouldQueue: false, shouldDefer: false, reason: '...' }` |
| `createInitialState` | L96–101 | Returns `{ initialized: false, configurationDone: false }` |
| `updateStateOnCommand` | L102–106 | Sets `state.configurationDone = true` on `'configurationDone'` command |
| `updateStateOnEvent` | L107–111 | Sets `state.initialized = true` on `'initialized'` event |
| `isInitialized` | L112–114 | Returns `state.initialized` |
| `isConnected` | L115–117 | Returns `state.initialized` (same as `isInitialized`) |
| `matchesAdapter` | L118–123 | True if command or joined args (lowercased) includes `'rdbg'` |
| `getInitializationBehavior` | L124–128 | `{ sendLaunchBeforeConfig: true }` — rdbg requires launch before configurationDone |
| `getEvaluateContext` | L133 | Returns `'repl'` — rdbg rejects `'variables'` context, accepts `'repl'` and `'watch'` |
| `getAttachBehavior` | L137 | `{ pauseAfterAttach: true }` — explicit pause needed on attach to running target |
| `getDapClientBehavior` | L138–155 | Handles `runInTerminal` reverse request; most child-session fields are `undefined`/`false` |
| `filterStackFrames` | L156–165 | Filters out frames where `frame.file` starts with `'<internal:'` or contains `'/gems/'` |
| `isInternalFrame` | L166–169 | True if `frame.file` starts with `'<internal:'` or contains `'/gems/'` |
| `getAdapterSpawnConfig` | L170–210 | **Attach mode**: validates port, returns `{ mode: 'connect', host, port, logDir }`. **Launch mode**: returns `{ mode: 'spawn', command, args, host, port, logDir, env }` |

---

### Notable Design Decisions

- **rdbg scope name fallback** (L35–37): Uses `presentationHint === 'locals'` as primary check with `name === 'Local variables'` as fallback, so a future rdbg rename won't break extraction.
- **Evaluate context** (L133): `'repl'` instead of DAP default `'variables'` because rdbg explicitly rejects unknown contexts.
- **Attach flow** (L137, L175–194): `pauseAfterAttach: true` and direct TCP `connect` mode — no adapter process spawned since rdbg already acts as a DAP server when started with `--open`.
- **validateExecutable** (L68–87): Checks both exit code 0 AND presence of output to guard against empty-output edge cases.
- **`isConnected` === `isInitialized`** (L115–117): Both return `state.initialized`; connection is considered established once the `initialized` event fires.

---

### Environment Variables Used

- `RUBY_PATH` (L58) — fallback Ruby executable path
- `RUBY_EXECUTABLE` (L58) — secondary fallback Ruby executable path

---

### Dependencies

- `@vscode/debugprotocol` — `DebugProtocol.Event`, `DebugProtocol.Scope`, `DebugProtocol.Request`
- `./adapter-policy.js` — `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` (interfaces this object satisfies)
- `@debugmcp/shared` — `SessionState` enum (used in `isSessionReady`)
- `../models/index.js` — `StackFrame`, `Variable` model types
- `./dap-client-behavior.js` — `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult`
- `child_process` (dynamic import at L69) — used only in `validateExecutable`