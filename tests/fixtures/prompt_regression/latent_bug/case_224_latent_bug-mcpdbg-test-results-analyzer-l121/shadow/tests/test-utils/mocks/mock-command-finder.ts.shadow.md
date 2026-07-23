# tests\test-utils\mocks\mock-command-finder.ts
@source-hash: 8985139ac91c4714
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:32Z

## MockCommandFinder (L10-73)

Test double implementing the `CommandFinder` interface from `@debugmcp/adapter-python`. Used in unit tests to simulate command path resolution without invoking the real OS-level executable lookup.

### Class: `MockCommandFinder` (L10-73)
Implements `CommandFinder`. Maintains two internal stores:
- `responses: Map<string, string | Error>` (L11) — maps command name → resolved path string or Error to throw
- `callHistory: string[]` (L12) — ordered log of every command passed to `find()`

### Key Methods

| Method | Lines | Purpose |
|---|---|---|
| `setResponse(command, response)` | L19-21 | Registers a mock result (path string or Error instance) for a named command |
| `find(command)` | L29-43 | Async interface method; records call, looks up response map; throws `CommandNotFoundError` if no entry, rethrows if entry is an `Error`, otherwise returns the path string |
| `clearResponses()` | L48-50 | Empties the responses map |
| `getCallHistory()` | L55-57 | Returns a shallow copy of `callHistory` (defensive copy prevents external mutation) |
| `clearHistory()` | L62-64 | Resets `callHistory` to empty array |
| `reset()` | L69-72 | Convenience method; calls both `clearResponses()` and `clearHistory()` |

### Behavior Notes
- `find()` (L34-36): If a command has **no registered response**, it throws `CommandNotFoundError(command)` — matching the production adapter's behavior for missing executables.
- `find()` (L38-40): If the registered response is an `Error` instance, it is re-thrown as-is, allowing tests to simulate arbitrary error conditions beyond `CommandNotFoundError`.
- `getCallHistory()` returns a copy (spread at L56), so test assertions cannot accidentally mutate the internal history.

### Dependencies
- `CommandFinder` (type import) from `@debugmcp/adapter-python` — interface being mocked
- `CommandNotFoundError` (value import) from `@debugmcp/adapter-python` — thrown for unregistered commands to mirror production behavior