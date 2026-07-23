# examples\rust\hello_world\src\main.rs
@source-hash: 55d7e2fa9b5f2ac5
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:17Z

## Purpose
A minimal Rust "hello world" program designed as a debugging demonstration target for MCP Debugger. Exercises common debugger workflows: variable inspection, breakpoints, stepping, collection mutation, and loop iteration.

## Key Symbols

### `main` (L9–38)
Entry point. Sequentially executes:
- **L10**: Prints greeting `"Hello, MCP Debugger!"`
- **L13–15**: Declares three typed locals for variable inspection: `name: &str`, `version: f64`, `is_awesome: bool`
- **L18–19**: Calls `calculate_sum(5, 10)`, prints result
- **L22–23**: Creates `Vec<i32>` via `vec!` macro, pushes element 6
- **L26–27**: Formats and prints a string interpolating `name` and `version`
- **L30–32**: Conditional branch on `is_awesome`
- **L35–37**: `for` loop over range `0..3` — intended breakpoint/step target

### `calculate_sum` (L40–44)
Pure function, `(a: i32, b: i32) -> i32`. Adds two integers and returns the sum. Comment at L41 explicitly marks it as a suggested breakpoint location for parameter inspection.

## Architectural Notes
- No external crate dependencies; uses only Rust stdlib macros (`println!`, `format!`, `vec!`)
- All variables in `main` are intentionally diverse in type to facilitate debugger variable-panel demonstrations
- `numbers` is the only `mut` binding, allowing mutation inspection after `push`
- `calculate_sum` is the only non-`main` function, kept trivial to keep debug stepping predictable