# Bug Analysis: Stale String Contract After Refactor

## The Bug

After running `docstar audit --full`, the scorecard footer reports:

```
*Phases not run: `--dead-code`, `--dead-deps`, `--orphaned-files`.
 Re-run with those flags for a complete scorecard.*
```

But the report body *above* the footer shows findings from all three
phases. They ran. The footnote is wrong.

## Root Cause

Two modules communicate through a `list[str]` called `junk_sources`.
The **producer** (`scorecard.py:build_scorecard`) appends the
analyzer's `.name` property to `junk_sources`. The **consumer**
(`audit.py:_format_scorecard_section`) checks membership using
hardcoded string literals. After a refactor, the producer changed
what strings it writes, but the consumer was never updated.

```
Producer (scorecard.py)         Consumer (audit.py)
─────────────────────────       ─────────────────────────
junk_sources.append(            if "dead_symbol" not in
  analyzer.name)                    scorecard.junk_sources:
                                    → "dead_code"
  → "dead_code"                 ✗ never matches
  → "dead_deps"
  → "orphaned_files"            if "dead_dependency" not in ...
                                    → "dead_deps"
                                ✗ never matches

                                if "orphaned_file" not in ...
                                    → "orphaned_files"
                                ✗ never matches (singular vs plural)
```

The condition is always true. The message always prints.

## How It Happened: Git Timeline

### Commit 276bbe1 — "Add scorecard phase" (2026-02-23)

Both `build_scorecard` and `_format_scorecard_section` are created.
At this point only two optional phases exist (dead-code, dead-plumbing).
The scorecard producer uses **finding category names** as the key:

```python
# scorecard.py — producer
junk_sources.append("dead_symbol")      # category name for dead code

# audit.py — consumer
if "dead_symbol" not in scorecard.junk_sources:   # ✓ matches
```

**The contract holds.** Both sides use the same string. But the string
is a magic literal duplicated across two files with no shared definition.

### Commit 3ed22ff — "Add junk analysis framework" (2026-02-25)

A unified `JunkAnalyzer` base class is introduced. Five analyzers are
registered in a `JUNK_ANALYZERS` list. Each has a `.name` property
(`"dead_code"`, `"dead_deps"`, `"dead_cicd"`, `"orphaned_files"`,
`"dead_plumbing"`).

The producer changes to a generic loop:

```python
# scorecard.py — new producer path
for analyzer_name, result in junk_results.items():
    junk_sources.append(analyzer_name)   # ← now uses analyzer.name
```

The old path (using `"dead_symbol"`) is kept as backward compat but is
unreachable when the new path is active.

The consumer gets three new checks added for the three new analyzers,
but the author **guessed** the key names instead of reading them from
the analyzer classes:

```python
# audit.py — consumer (wrong)
if "dead_symbol" not in ...       # stale — should be "dead_code"
if "dead_dependency" not in ...   # invented — should be "dead_deps"
if "orphaned_file" not in ...     # singular — should be "orphaned_files"
if "dead_cicd" not in ...         # correct (lucky guess)
```

**The contract breaks in one commit.** The producer now writes
`analyzer.name` values; the consumer still checks a mix of old
category names and newly-invented-but-wrong names.

## The Pattern That Failed

### Implicit String Contract

Two modules agree on a set of valid string values, but that agreement
is encoded only by **duplicating the same literal in both places**.
There is no shared definition — no enum, no constant, no type.

This pattern has three properties that make it fragile:

1. **Invisible coupling.** Nothing in the code declares that the
   producer and consumer must agree. `grep` for the string finds both
   sites, but only if you know to grep. An IDE won't flag a mismatch.

2. **Silent failure.** A wrong string doesn't crash. The membership
   test `x not in list` returns True (the "not found" branch), which
   is a valid execution path — it just means "this phase didn't run."
   The code does something reasonable-looking either way.

3. **Refactor-fragile.** When one side is rewritten (category names →
   analyzer names), the other side has no structural reason to change.
   It still compiles, still runs, still produces output. The output is
   just wrong.

### Why the Fix Works but Isn't the Lesson

The fix replaces the hardcoded strings with a loop over the
`JUNK_ANALYZERS` registry:

```python
for analyzer_cls in JUNK_ANALYZERS:
    a = analyzer_cls()
    if a.name not in scorecard.junk_sources:
        missing.append(f"`--{a.cli_flag}`")
```

This eliminates the duplication — the consumer now reads from the same
source of truth as the producer. But the deeper lesson isn't "use a
loop." It's: **when two sites must agree on a value, make them derive
it from one place.**

The pattern that broke was **duplicated string literals as implicit
protocol**. The fix pattern is **single source of truth**. But there
are other ways to enforce the same constraint: a shared enum, a
constant dict, a type system, or a test.

## Detection Strategies

### 1. LLM Code Review Prompt

The following instruction, given to an LLM reviewing a diff or a
codebase, would catch this class of bug:

> **String membership orphan check.** For every expression of the form
> `"literal" in collection` or `"literal" not in collection`, verify
> that the literal value is actually produced somewhere upstream —
> i.e., that some code path appends/inserts that exact string into
> that collection. If the literal appears only in the consumer
> (the membership test) and never in the producer (the code that
> populates the collection), the check is dead. Flag it.
>
> Pay special attention when:
> - The collection is populated by a loop or generic code (e.g.,
>   `for name, val in items: coll.append(name)`) but checked with
>   hardcoded literals.
> - The collection and the check are in different files/modules.
> - A recent refactor changed how the collection is populated.

### 2. Diff-Aware Review Prompt

For reviewing a specific commit or PR:

> **Contract drift check.** When a refactor changes how a shared data
> structure (dict, list, set) is populated, find every consumer of
> that data structure and verify the consuming code still uses values
> that the producer actually emits. If the producer changed from
> writing hardcoded strings to writing dynamic values (e.g., from
> object properties), every hardcoded consumer check must be updated
> or replaced with a dynamic equivalent.

### 3. Static Analysis (Achievable)

A tractable static analysis pass:

1. Find all expressions of the form `"X" [not] in <var>`.
2. Trace `<var>` to where it is populated (append, extend, assignment).
3. If the producer is a loop that appends values from a dynamic source
   (attribute access, function call, dict key), and the consumer uses
   a hardcoded literal, emit a warning:
   *"Membership test uses hardcoded literal but collection is
   populated dynamically. Consider deriving the test value from the
   same source."*

This doesn't require solving the halting problem. It's a heuristic
that flags the *structural mismatch* (hardcoded vs. dynamic) rather
than trying to prove the string values are wrong.

### 4. Runtime / Test Detection

A simple integration test:

```python
def test_full_audit_no_missing_phases(tmp_codebase):
    result = run_audit(tmp_codebase, full=True)
    report = format_audit_report(result)
    assert "Phases not run" not in report
```

This is the cheapest backstop. It doesn't prevent the pattern from
recurring elsewhere, but it catches this specific instance.

## Generalised Rule

> **When two code sites must agree on a set of string (or enum, or
> key) values, they must derive those values from a single shared
> definition. Duplicating the values as literals in both sites creates
> an implicit contract that is invisible to compilers, linters, and
> most reviewers. The failure mode is silent: the wrong branch
> executes without error.**
>
> If you find yourself writing `if "X" not in collection` where
> `collection` is built by code you don't control, stop and ask:
> where does "X" come from? If the answer is "I know the producer
> uses this string," you've created an implicit contract. Make it
> explicit.
