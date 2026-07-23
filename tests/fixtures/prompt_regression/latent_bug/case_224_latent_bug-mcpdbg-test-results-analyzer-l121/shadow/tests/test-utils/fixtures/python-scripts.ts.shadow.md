# tests\test-utils\fixtures\python-scripts.ts
@source-hash: 86c3e55789ec2587
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:25Z

## Python Script Fixtures for Debugger Testing

This file exports a set of TypeScript string constants, each containing an embedded Python script. These fixtures are used in tests to exercise various debugger features (breakpoints, step-through, exception handling, multi-module imports, etc.).

---

### Exported Constants

| Constant | Lines | Python Script Description |
|---|---|---|
| `simpleLoopScript` | L8–23 | Basic `for` loop summing `range(5)`; tests simple step-through and variable tracking. |
| `functionCallScript` | L26–53 | Two functions (`add`, `multiply`) called from `main`; tests function-call step-in/step-over. |
| `fibonacciScript` | L56–99 | Recursive and iterative Fibonacci implementations with an `assert` to verify results match; tests recursion and assertion breakpoints. |
| `exceptionHandlingScript` | L102–134 | `divide` with `ZeroDivisionError` catch and `IndexError` catch; tests breakpoints on caught exceptions. |
| `multiModuleMainScript` | L137–152 | Imports `module_helper` and calls `module_helper.process_data`; tests cross-module debugging. Must be paired with `multiModuleHelperScript`. |
| `multiModuleHelperScript` | L155–171 | Standalone helper module defining `process_data`; returns a dict with `total`, `average`, `min`, `max`. Designed to be written as a separate file alongside `multiModuleMainScript`. |
| `buggyScript` | L174–212 | `calculate_average` intentionally only counts positive numbers (`if number > 0`), causing incorrect averages and a `ZeroDivisionError` for all-negative lists; tests debugging a known bug. |

---

### Usage Pattern

- All constants are plain template-literal strings — they are not executed here.
- Tests typically write these strings to temporary `.py` files on disk, then launch a debugger session against them.
- `multiModuleMainScript` and `multiModuleHelperScript` must be written to the same directory as `main.py` and `module_helper.py` respectively for the import to resolve.

---

### Notable Design Details

- `buggyScript` has an intentional bug documented in its embedded comment (L183–184): `count` only increments for positive numbers, so "average" is actually the average of positive numbers only, not all numbers. The fixture is used to test that a developer can discover this via debugger inspection.
- `fibonacciScript` uses `assert` (L93) — relevant for tests verifying behavior on assertion errors or assertion-enabled debugger modes.
- No runtime TypeScript logic exists in this file; it is purely a data module.