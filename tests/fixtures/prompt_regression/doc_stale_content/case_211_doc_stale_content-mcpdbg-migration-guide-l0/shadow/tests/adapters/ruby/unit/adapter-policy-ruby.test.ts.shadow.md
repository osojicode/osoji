# tests\adapters\ruby\unit\adapter-policy-ruby.test.ts
@source-hash: 81d50c4805201069
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:11Z

## Unit Tests: RubyAdapterPolicy and buildRdbgInvocation

Test suite validating the Ruby debug adapter policy and the `buildRdbgInvocation` helper. Tests cover the spawn-config matrix introduced with the direct-connect redesign.

### Test Structure

**`RubyAdapterPolicy.getAdapterSpawnConfig` (L27–108)**
- `attach` request → `{ mode: 'connect', host, port, logDir }` with validated host (defaults to `127.0.0.1`) and port (L28–50)
- Port validation: throws `/Ruby attach requires a valid TCP port/` for missing, zero, negative, out-of-range (`70000`), and non-numeric values (L52–65)
- Regression test: never silently falls back to proxy `adapterPort` on attach (L67–76)
- `launch` request → `{ mode: 'spawn', command, args, host, port, logDir, env }` echoing `adapterCommand` (L78–98)
- Throws `/adapter command/i` for launch without `adapterCommand` (L100–107)

**`RubyAdapterPolicy hooks` (L110–156)**
- `matchesAdapter`: detects rdbg commands (direct binary or via ruby.exe on Windows), rejects non-Ruby adapters (L111–118)
- `getEvaluateContext`: returns `'repl'` (rdbg rejects `"variables"` context) (L120–122)
- `getAttachBehavior`: returns `{ pauseAfterAttach: true }` (L124–126)
- `extractLocalVariables`: selects variables from the `'Local variables'` scope only (variablesReference 7), excludes `'Global variables'` (L128–143)
- `filterStackFrames`: filters `<internal:*>` and gem paths (`/usr/lib/gems/...`) when `showInternal=false`; returns all 3 frames when `showInternal=true` (L145–155)

**`RubyAdapterPolicy behavior surface` (L158–239)**
- `getDapAdapterConfiguration`: returns `{ type: 'rdbg' }` (L160)
- `getDebuggerConfiguration`: `requiresStrictHandshake: false`, `supportsVariableType: true` (L161–163)
- `getInitializationBehavior`: `{ sendLaunchBeforeConfig: true }` (L165)
- `requiresCommandQueueing`: `false` (L166)
- `shouldQueueCommand('next', ...)`: `{ shouldQueue: false, shouldDefer: false }` (L167–170)
- `shouldDeferParentConfigDone`: `false` (L171)
- `isChildReadyEvent`: `true` for `{ event: 'initialized' }`, `false` for `{ event: 'stopped' }` (L172–173)
- `buildChildStartArgs`: throws `/child sessions/` (L174)
- `resolveExecutablePath`: returns explicit path or falls back to `RUBY_PATH` env var (L177–181)
- State machine: `createInitialState` → `isInitialized=false/isConnected=false`; after `'initialized'` event → both `true`; after `'configurationDone'` command → `state.configurationDone=true` (L183–194)
- `isSessionReady`: `true` for `'paused'`, `false` for `'running'` (L196–199)
- `getDapClientBehavior().handleReverseRequest`: handles `'runInTerminal'` (calls `sendResponse`, returns `{ handled: true }`); returns `{ handled: false }` for `'startDebugging'` (L201–216)
- `validateExecutable`: spawns `--version`, resolves `true` for valid executable (`process.execPath`), `false` for non-existent path (L218–221)
- `isInternalFrame`: `true` for `<internal:kernel>` and gem paths, `false` for workspace files (L223–227)
- `extractLocalVariables` edge cases: empty frames, empty scopes, no matching local scope → returns `[]` (L229–238)

**`getPolicyForLanguage` (L241–250)**
- Maps `DebugLanguage.RUBY` and string `'ruby'` to `RubyAdapterPolicy` (L243–244)
- Returns policy with `name === 'default'` for unknown languages like `'fortran'` (L248)

**`buildRdbgInvocation` (L252–286)**
- Non-Windows: passes through `{ command, args }` unchanged (L262–266)
- Windows `.bat` shim (RubyInstaller layout): rewrites to `{ command: rubyExe, args: [siblingRdbgScript, ...args] }` when sibling `rdbg` script exists alongside `rdbg.bat` (L269–280)
- Windows, no sibling script: throws `/Set RDBG_PATH to the rdbg Ruby script/` (L282–285)
- Uses `fs.mkdtempSync` in `os.tmpdir()` for temp fixture creation; cleaned up via `afterEach` with `fs.rmSync` (L253–260)

### Key Fixtures
- `basePayload` (L19–25): shared base for spawn-config tests — `executablePath`, `adapterHost`, `adapterPort: 4711`, `logDir`, `scriptPath`

### Dependencies
- `RubyAdapterPolicy`, `getPolicyForLanguage`, `DebugLanguage` from `@debugmcp/shared`
- `buildRdbgInvocation` from `@debugmcp/adapter-ruby`
- `DebugProtocol.Scope` type from `@vscode/debugprotocol` for scope fixture typing (L130)
- `vi.stubEnv` for `RUBY_PATH` env var stubbing (L179–180)
- `fs`, `os`, `path` (Node.js builtins) for temp-dir fixture in `buildRdbgInvocation` tests