# examples\java\RedefineTarget.java
@source-hash: f34c332e0f536388
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:43Z

## RedefineTarget (L8-27)

Test fixture for JVM hot-reload (`redefine_classes`) integration testing. This class is designed to be loaded by a debugger test harness, which:
1. Attaches to the JVM process.
2. Sets breakpoints at the two `getValue()` call sites (L18 and L22).
3. Verifies `getValue()` returns `42` before hot-swap.
4. Replaces this class's bytecode with a `RedefineTargetV2` variant (which returns `99`).
5. Verifies `getValue()` now returns `99` after the hot-swap.

### Key Elements

- **`RedefineTarget` class (L8-27):** Top-level public class; entry point and target for bytecode redefinition.
- **`getValue()` (L10-12):** Package-private static method returning the integer literal `42`. This is the method replaced during hot-swap. The comment on L11 documents the expected post-swap return value (`99`).
- **`main(String[])` (L14-26):** Entry point. Sleeps for 2 seconds (L16) to allow the test harness to attach and configure breakpoints before execution proceeds. Calls `getValue()` twice: once before (L18) and once after (L22) the expected hot-swap window, printing results.

### Architectural Role

Pure test fixture — no production logic. Relies entirely on an external debugger/test harness (not present in this file) to perform the JDWP `RedefineClasses` operation between the two `getValue()` invocations. The 2-second sleep (L16) is the synchronization primitive that gives the harness time to act.

### Important Constraints / Invariants

- Line numbers are load-bearing: the test harness targets breakpoints by **line number** (L18 for first call, L22 for second call). Any reformatting that shifts these lines will break the test.
- The class must be compiled with debug info (`-g`) so the JDWP agent can resolve line-number breakpoints.
- The companion class `RedefineTargetV2` (external file, not shown) must be binary-compatible and return `99` from `getValue()`.
