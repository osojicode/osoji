# tests\test-utils\helpers\port-manager.ts
@source-hash: 8c4ded64e0ef8cd6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:39Z

## Test Port Manager (`tests/test-utils/helpers/port-manager.ts`)

Provides centralized, conflict-free port allocation for test suites. Maintains an in-memory registry of used ports and exposes a singleton `portManager` instance for shared use across tests.

---

### Constants

- **`BASE_PORT`** (L9): `5679` — starting port for all allocations. All range offsets and fallback scans are relative to this value.

---

### `PortRange` enum (L12–16)

Numeric offsets added to `BASE_PORT` to segment allocations by test type:

| Member | Value | Effective Range |
|---|---|---|
| `UNIT_TESTS` | `0` | 5679–5778 |
| `INTEGRATION` | `100` | 5779–5878 |
| `E2E` | `200` | 5879–5978 |

Each range has a size of 100, configured in the constructor (L29–31).

---

### `TestPortManager` class (L18–102) — internal

State:
- `basePort: number` — fixed at `BASE_PORT` (5679)
- `usedPorts: Set<number>` — tracks currently allocated ports
- `rangeSizes: Map<PortRange, number>` — range → size (all 100)

#### Methods

| Method | Lines | Signature | Description |
|---|---|---|---|
| `getPort` | L39–63 | `(range?: PortRange) → number` | Allocates the lowest unused port in the specified range. Falls back to scanning 5679–6678 if the range is exhausted. Throws if all 1000 fallback ports are used. |
| `releasePort` | L69–71 | `(port: number) → void` | Removes a port from `usedPorts`, making it available for re-allocation. |
| `reset` | L76–78 | `() → void` | Clears all tracked ports; use between test suites. |
| `isPortInUse` | L85–87 | `(port: number) → boolean` | Returns `true` if `port` is currently allocated. |
| `getPorts` | L95–101 | `(count: number, range?: PortRange) → number[]` | Convenience wrapper: allocates `count` ports from the specified range by calling `getPort` repeatedly. |

#### Allocation Strategy
1. Scan the requested `PortRange` window linearly for the first unused port (L45–50).
2. If that window is full, scan the entire 1000-port space starting at `BASE_PORT` (L54–59).
3. If all 1000 are used, throw a descriptive `Error` (L62).

---

### Exported Singleton

- **`portManager`** (L105): single shared `TestPortManager` instance — imported by test helpers to guarantee no two tests receive the same port within a process lifetime.
- Also exported as `default` (L107).

---

### Usage Pattern

```typescript
import { portManager, PortRange } from './port-manager';

const port = portManager.getPort(PortRange.INTEGRATION);
// ... run test server on port ...
portManager.releasePort(port);
```

---

### Important Constraints / Invariants

- Port tracking is **in-memory only** — does not verify OS-level socket availability. Two processes running concurrently may still collide unless port ranges are partitioned externally.
- `reset()` should be called between isolated test runs; otherwise allocations persist for the lifetime of the singleton (module cache).
- The fallback scan (L54–59) can allocate ports that cross range boundaries, potentially causing semantic conflicts between test types.