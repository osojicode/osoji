# scripts\llm-env.ps1
@source-hash: 4c73736cac9acd9c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:59Z

## Purpose
PowerShell dot-source script that overrides shell-level commands (`npm`, `docker`) and adds `git-clone` to reduce test output noise for LLM token efficiency. Must be sourced (`. ./scripts/llm-env.ps1`) to inject function overrides into the current session.

## Key Functions

### `npm` (L16–147)
Overrides the `npm` command via PowerShell function shadowing. Dispatches on `$argsString` pattern matching:

- **`test` / `run test`** (L21–93): Sets `$env:CI = 'true'`, then:
  - If extra args follow `test`, delegates to `npm.cmd test @testArgs` (L46) — passes specific test files through unfiltered.
  - Otherwise runs `npm.cmd run test:coverage -- --reporter=tap` (L51) and applies a TAP stream filter:
    - Shows TAP header lines, plan lines (`\d+\.\.\d+`), and comment lines (`^#`) always.
    - Shows coverage table rows (lines matching `%`, `---|`, `File |`, `All files |`, or numeric cell patterns).
    - Tracks `not ok \d+ - .*\.ts` to enter `$inFailure` mode; shows all subsequent lines until a bare `}` at file level (L84).
    - Tracks `ok \d+ - .*\.ts` to enter `$skipDepth > 0` mode; suppresses nested JSON block content by counting `{`/`}`.
- **`test:unit`** (L95–110): Sets CI, runs `npm.cmd run test:unit -- --reporter=tap --coverage`, applies a simpler per-assertion TAP filter (show `not ok` lines and their indented details; suppress `ok` lines).
- **`test:int`** (L111–126): Same pattern as `test:unit` but runs `test:integration`.
- **`test:e2e`** (L127–142): Same pattern but runs `test:e2e`.
- **All other npm commands** (L143–146): Pass-through via `& npm.cmd @args`.

### `docker` (L150–176)
Overrides `docker`. Intercepts `docker build ...` (L155) and injects `--progress=plain` after the `build` argument if not already present (L158–165), then delegates to `docker.exe`. All other docker subcommands pass through unchanged (L173–175).

### `git-clone` (L178–181)
New wrapper (not an override of `git`). Runs `git.exe clone --quiet @args`.

### `Show-LLMHelpers` (L184–193)
Prints a summary of all active overrides and their behavior to the console. Called manually; also referenced in the load message (L197).

## Module-Level Behavior (L196–197)
On dot-source, prints a green confirmation message and prompts the user to type `Show-LLMHelpers`.

## Architectural Notes
- **Session-scope injection**: Works only when dot-sourced; running the script normally creates a subprocess and overrides are lost.
- **`npm.cmd` / `docker.exe` / `git.exe`**: Direct executable calls bypass the overridden functions, preventing infinite recursion.
- **TAP filter state machine** (`$inFailure`, `$skipDepth`): Inline stateful stream processing within `ForEach-Object` pipeline. The full-test filter (L49–92) and per-command filters (L98–109, L113–125, L131–141) use slightly different logic.
- **`$env:CI = 'true'`**: Set for all intercepted test runs to disable interactive/dynamic terminal output from test runners.
- **Smart quote warning** (L12–13): Editors that auto-convert `'` to `'`/`'` will break PowerShell string literals.

## TAP Filter Logic Detail (Full Test Run, L49–92)
State variables reset per invocation:
- `$inFailure = $false`: Tracks whether currently inside a failed-test block.
- `$skipDepth = 0`: Tracks brace-nesting depth when skipping a passing-test block.

Priority order of line dispatch (first match wins):
1. TAP structural lines → always print.
2. Coverage table lines → always print.
3. `not ok \d+ - .*\.ts` → set `$inFailure = $true`, print.
4. `ok \d+ - .*\.ts` → set `$skipDepth = 1` (enter skip mode), suppress.
5. `$skipDepth > 0` → count `{`/`}`, suppress; when depth returns to 0, `return` (skip closing brace).
6. `$inFailure` → print; if line is exactly `}`, exit failure mode.
7. Empty lines / terminal prompts → print.
8. (Implicit) Anything else → suppressed.

## Potential Issues
- The specific test file pass-through branch (L46) does not apply the TAP filter or set coverage flags — output is raw.
- `$skipDepth` depth tracking assumes TAP JSON blocks use bare `{`/`}` lines, which depends on the test reporter's exact format.
- `test:int` pattern (L111) matches on `^(run )?test:int`, which also matches `test:integration` if typed that way — intentional abbreviation match.