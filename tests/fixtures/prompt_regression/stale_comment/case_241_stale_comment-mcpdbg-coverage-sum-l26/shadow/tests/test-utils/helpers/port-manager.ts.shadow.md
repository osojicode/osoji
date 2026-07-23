# tests\test-utils\helpers\port-manager.ts
@source-hash: 8c4ded64e0ef8cd6
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:32Z

## Test Port Manager (`tests/test-utils/helpers/port-manager.ts`)

Provides a centralized, conflict-avoiding port allocation system for concurrent test runs. Exports a singleton `portManager` instance of the internal `TestPortManager` class.

### Constants
- **`BASE_PORT`** (L9): `5679` — All port allocations start from this base.

### `PortRange` Enum (L12–16)
Numeric offsets from `BASE_PORT` used to segment port space by test type:
| Member | Offset | Effective Range |
|---|---|---|
| `UNIT_TESTS` | 0 | 5679–5778 |
| `INTEGRATION` | 100 | 5779–5878 |
| `E2E` | 200 | 5879–5978 |

> Note: Comments in the enum body accurately describe these ranges.

### `TestPortManager` Class (L18–102) — internal
Manages port allocation state via two private data structures:
- `usedPorts: Set<number>` — tracks currently allocated ports.
- `rangeSizes: Map<PortRange, number>` — maps each range to a size of 100.

#### Methods
| Method | Lines | Signature | Description |
|---|---|---|---|
| `getPort` | L39–63 | `(range?: PortRange) → number` | Allocates the first unused port in the specified range. Falls back to scanning all 1000 ports from `BASE_PORT` if the preferred range is exhausted. Throws if all fallback ports are also exhausted. |
| `releasePort` | L69–71 | `(port: number) → void` | Removes a port from `usedPorts`, making it available for reallocation. |
| `reset` | L76–78 | `() → void` | Clears all tracked port allocations (useful in `afterEach`/`afterAll` hooks). |
| `isPortInUse` | L85–87 | `(port: number) → boolean` | Returns `true` if the port is currently tracked as allocated. |
| `getPorts` | L95–101 | `(count: number, range?: PortRange) → number[]` | Allocates `count` ports from the specified range by calling `getPort` repeatedly. |

### Singleton Export (L105)
```ts
export const portManager = new TestPortManager();
export default portManager;
```
Both named and default exports resolve to the same singleton instance. All state is shared across imports within a single Node.js process.

### Allocation Algorithm
1. Scan `[rangeStart, rangeEnd]` sequentially for an unclaimed port.
2. If the preferred range is exhausted, scan `[BASE_PORT, BASE_PORT+999]` as a fallback.
3. If both are exhausted, throw an `Error` with a descriptive message.

### Usage Pattern
```ts
import { portManager, PortRange } from './helpers/port-manager';

const port = portManager.getPort(PortRange.INTEGRATION);
// ... run test using port ...
portManager.releasePort(port);
```

### Architectural Notes
- **No OS-level availability check**: The manager tracks only its own allocations. Ports already bound by external processes (e.g., other test runners, system services) are not detected.
- **Process-scoped singleton**: Sharing state across concurrent *worker threads* or *child processes* requires separate synchronization; this implementation is not multi-process safe.
- **Sequential allocation**: Ports are always allocated from the lowest available number upward, which may cause clustering under high concurrency.