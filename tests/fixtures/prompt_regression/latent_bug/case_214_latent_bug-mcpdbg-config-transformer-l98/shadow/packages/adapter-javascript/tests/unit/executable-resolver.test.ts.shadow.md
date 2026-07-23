# packages\adapter-javascript\tests\unit\executable-resolver.test.ts
@source-hash: 504ce6a9909701ed
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:19Z

## Unit Tests: `executable-resolver` utilities

Tests for `findNode` and `whichInPath` functions from `packages/adapter-javascript/src/utils/executable-resolver.ts`, using a controlled `MockFileSystem` to avoid real filesystem access.

### Test Structure

**Suite:** `utils/executable-resolver: findNode and whichInPath` (L30–106)

**Setup pattern (L33–43):**
- `beforeEach`: Instantiates a fresh `MockFileSystem`, injects it via `setDefaultFileSystem(mockFileSystem)`
- `afterEach`: Calls `vi.restoreAllMocks()` and resets the default filesystem back to a real `NodeFileSystem`

---

### Key Components

#### `MockFileSystem` (L11–24)
Implements the `FileSystem` interface from `@debugmcp/shared`. Exposes:
- `setExistsMock(mock)` (L14): Injects a custom predicate for `existsSync`
- `existsSync(path)` (L18): Delegates to injected mock or returns `false` by default

#### `withPath(paths: string[])` (L26–28)
Helper that stubs `process.env.PATH` via `vi.stubEnv`, joining the provided array with the platform delimiter (`path.delimiter`).

#### `WIN` constant (L6)
Captures the result of `isWindows()` at module load time to branch expected filenames (`.exe` suffix on Windows) in test assertions.

---

### Test Cases

| Test | Line | Behavior Verified |
|------|------|-------------------|
| `findNode` returns `process.execPath` when it exists | L45–50 | Default resolution when no preferred path; result is `path.resolve(process.execPath)` |
| `preferredPath` takes precedence | L52–58 | If a preferred path is passed and exists, it is returned directly |
| PATH fallback when `execPath` is bypassed | L60–76 | When `execPath` mock returns `false`, first matching entry from PATH is resolved |
| `whichInPath` dir-first precedence | L78–96 | Directory order dominates name order: `dirA/nodeB` found before `dirB/nodeA` |
| Negative: no matches returns `process.execPath` deterministically | L98–105 | Even with empty PATH and all `existsSync` returning `false`, `findNode` falls back to `path.resolve(process.execPath)` |

---

### Architectural Notes
- Uses **dependency injection** of `FileSystem` abstraction via `setDefaultFileSystem` to decouple filesystem access from tests — no real disk I/O occurs.
- `isWindows()` is called **at module load** (L6) so all tests share the same platform detection result; platform-specific filename branches (`.exe`) are handled in individual tests.
- `vi.stubEnv` (via `withPath`) automatically restores env vars on `vi.restoreAllMocks()` in `afterEach`.
- The `whichInPath` test (L78–96) documents the **precedence contract**: directory order in PATH beats name order in the candidate list.
