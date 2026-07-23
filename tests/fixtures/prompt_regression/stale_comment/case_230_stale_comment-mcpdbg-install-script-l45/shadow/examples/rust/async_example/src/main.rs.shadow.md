# examples\rust\async_example\src\main.rs
@source-hash: 41f1cf23315cb999
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:02Z

## Purpose
Async Rust demo using the Tokio runtime, intended as a debugging example for async/await, concurrent tasks, and future handling. Not a library — pure executable entry point.

## Key Symbols

### `main` (L12–40) — `async fn`, Tokio entry point
Orchestrates all async operations in sequence:
1. **Sequential await** (L16): calls `fetch_data(1).await` and prints the returned `String`.
2. **Concurrent spawn** (L20–22): spawns three `async_task` futures via `tokio::spawn`, producing `JoinHandle<u32>` for each.
3. **Join** (L25): uses `tokio::join!` macro to await all three handles simultaneously; results are a 3-tuple of `Result<u32, JoinError>`.
4. **Pattern match** (L27–32): destructures the tuple, printing results or a failure message.
5. **Async loop** (L35–37): sequentially awaits `process_item(i)` for `i` in `0..3`.

### `fetch_data(id: u32) -> String` (L42–47)
Simulates a data fetch with a 100ms `tokio::time::sleep` delay. Returns a formatted string `"Data_{id}"`. Breakpoint hint in comment at L43.

### `async_task(task_id: u32) -> u32` (L49–58)
Simulates variable-duration async work: sleeps for `task_id * 100` milliseconds. Returns `task_id * 10`.

### `process_item(item: u32)` (L60–64)
Simulates item processing with a fixed 50ms sleep. Returns `()`.

## Dependencies
- `tokio` (runtime + `time` feature): `sleep`, `Duration`, `tokio::spawn`, `tokio::join!`, `#[tokio::main]`

## Patterns & Architecture
- `#[tokio::main]` macro wraps `main` in a Tokio multi-threaded runtime.
- `tokio::spawn` is used for concurrent execution; tasks run on the Tokio thread pool.
- `tokio::join!` waits for all spawned tasks concurrently (not sequentially), giving parallel execution semantics.
- The async loop (L35–37) is **sequential** — each `process_item` fully completes before the next starts.
- No shared state, channels, or error propagation beyond the join match.
