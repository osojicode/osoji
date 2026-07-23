# src\implementations\environment-impl.ts
@source-hash: d509c4dea5c4799a
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:33Z

## `ProcessEnvironment` (L11–41)

Concrete implementation of the `IEnvironment` interface (from `@debugmcp/shared`) that wraps Node.js `process.env` and `process.cwd()`.

### Key Design Decisions

- **Snapshot at construction (L17):** `process.env` is shallow-copied into `this.envSnapshot` at instantiation time. This means the instance reflects the environment as it was when constructed, not live values. Mid-execution changes to `process.env` are intentionally ignored.
- **`getCurrentWorkingDirectory` is NOT snapshotted (L39):** Unlike env vars, `process.cwd()` is called live on every invocation — it reflects the actual current working directory at call time, not at construction time. This is an intentional asymmetry.
- **`getAll` returns a defensive copy (L32):** Callers cannot mutate the internal snapshot through the returned object.

### Methods

| Method | Lines | Behavior |
|---|---|---|
| `constructor()` | L14–18 | Snapshots `process.env` via spread |
| `get(key)` | L23–25 | Returns `string \| undefined` from snapshot |
| `getAll()` | L30–33 | Returns defensive copy of snapshot |
| `getCurrentWorkingDirectory()` | L38–40 | Calls `process.cwd()` live |

### Dependencies

- `IEnvironment` interface from `@debugmcp/shared` — this class must satisfy that contract. The interface defines `get`, `getAll`, and `getCurrentWorkingDirectory` signatures.