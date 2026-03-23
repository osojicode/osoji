# String Contract and Obligation Checking: Detecting Cross-File Implicit Contracts

## What are string contracts?

Many codebases contain pairs of files that must agree on a string value without any type system enforcement. These are *implicit contracts* -- they work as long as both sides use the same literal string, and they break silently when one side changes.

Here are common examples:

- **Routing frameworks.** A handler function registers itself with a string route name (`"user_profile"`), and a router dispatches requests by matching against the same string. If the handler renames its route but the router is not updated, requests silently fail to match.

- **Configuration systems.** A config file defines a key (`"max_batch_size"`), and multiple consumer modules read that key using string lookups (`config.get("max_batch_size")`). If the key is renamed in the config schema but not in the consumers, the consumers silently receive a default value.

- **Event systems.** An emitter publishes events using a string name (`"task_completed"`), and listeners subscribe to the same string. A typo or rename on either side causes the listener to never fire, with no error at build time.

- **API contracts.** A server defines endpoint paths as string literals (`"/api/v2/users"`), and a client references the same paths. A path change on the server side causes client requests to 404 without any compile-time warning.

In all these cases, the string literal acts as a *name* -- an identifier that must be consistent across files. Unlike import statements (which produce `ImportError` on mismatch) or type annotations (which produce type checker warnings), string contract violations produce silent runtime failures. The obligation checker in `src/osoji/obligations.py` exists to surface these risks.

## How the StringContractChecker works

The `StringContractChecker` class in `obligations.py` implements the `ContractChecker` ABC and performs two distinct analyses: violation detection and fragility detection. Both operate on structured facts extracted from `.osoji/facts/` sidecar files -- specifically the `string_literals` field, which classifies each string by its `kind` and `usage`.

### String literal classification

During shadow documentation generation, string literals are extracted and classified with several fields:

- **`kind`**: Distinguishes identifier strings (names, keys, routes) from user-facing strings (error messages, log text). The checker focuses on strings with `kind == "identifier"` -- strings that function as names in cross-file contracts rather than human-readable text.

- **`usage`**: Classifies how the string is used: `"produced"` (created as output, e.g., a return value or dict value), `"checked"` (compared against, e.g., in an equality check), or `"defined"` (assigned to a constant).

- **`comparison_source`**: For checked strings, records *what* the string is compared against (e.g., `request.method`, `config.get("key")`), enabling heuristic filtering of external protocol values.

### Ratio-based violation detection (core algorithm)

The violation detection algorithm in `_check_violations` uses a ratio-based approach to distinguish internal contract violations from external API usage. The algorithm processes each non-test file independently:

1. **Collect checked identifier strings.** For each file, gather all string literals with `usage == "checked"` and `kind == "identifier"`, filtering out occurrences that match heuristic exclusion patterns (external origins, file path checks, serialized key reads, external protocol literals, duck-typing patterns).

2. **Remove tool names.** Tool names (from Osoji's own LLM tool definitions) are removed from the checked values set before the match/unmatch split.

3. **Split matched vs unmatched.** The set of checked values is intersected with the global set of produced/defined values (from all files). Values present in the global set become `matched`; the rest become `unmatched`.

4. **Post-filter unmatched only.** Noise filtering -- tool schema keys, common strings (like `"id"`, `"name"`, `"type"`), and strings shorter than 3 characters -- is applied only to the `unmatched` set, not to `matched`. This means matched values are preserved regardless of length or commonality.

5. **Compute the match ratio.** The ratio uses the original `checked_values` length (after tool-name removal but before noise filtering) as the denominator: `len(matched) / len(checked_values)`. Because noise filtering only removes from `unmatched`, short or common strings that happen to match producers still count toward the numerator.

6. **Apply the ratio logic:**
   - If *some* checked strings match producers/definers but others do not, the unmatched strings are violations. The confidence equals the match ratio.
   - If *zero* checked strings match any producer (ratio = 0), the entire set is treated as external references and skipped entirely.

The zero-ratio escape hatch is critical for avoiding false positives. A file that checks strings like `"GET"`, `"POST"`, `"application/json"` against an HTTP request object is using external protocol values, not internal project contracts. Since none of these match any project-internal producer, the ratio is zero and the file is skipped. Without this rule, every file interacting with external APIs would generate spurious violations.

When the ratio is non-zero, it means the file participates in *some* internal contracts (the matched strings prove this). The unmatched strings in the same file are then suspicious -- they look like they should match an internal producer but do not.

### Fragility detection

The fragility algorithm in `_check_fragility` finds a different class of problem: string values that are both produced and checked across different files, but with no shared definition linking them. These are not violations today -- the strings match and the code works. But they are *fragile*: a rename on either side will silently break the contract.

The algorithm:

1. **Find shared values.** Identify string values that appear in both the `producers` dict (values with `usage == "produced"`) and the `checked` dict (values with `usage == "checked"`).

2. **Check cross-file pairs.** For each producer-file and checker-file pair that shares a value, determine whether they are linked through a shared definer file.

3. **Evaluate linkage.** A contract is *robust* if both the producer and checker are linked (via imports, directly or one hop) to a file that defines the value as a constant. The `_files_are_linked` method uses `FactsDB.imports_of` to check import relationships up to one hop.

4. **Flag fragile contracts.** If no shared definer links producer and checker, the contract is fragile. The finding has `finding_type="implicit_contract"` and `severity="info"`.

Fragile contract findings are grouped by file pair using `_group_findings`. When a pair shares more than 3 implicit contracts, the remediation text explains the value-level vs name-level error distinction:

> These files share N implicit string contracts. If they have a known dependency (e.g. one file tests the other), this may be expected. Otherwise, consider extracting shared values to a common definition so a rename triggers an import error instead of a silent mismatch.

This remediation reflects Osoji's design principle of surfacing silent failures: the goal is to convert value-level mismatches (which fail silently at runtime) into name-level errors (which fail loudly at import time).

## Import-link analysis

The checker uses the `FactsDB` import graph to determine whether producer and consumer files are explicitly linked. This analysis is central to fragility detection:

- **Linked files** have an explicit dependency chain: the consumer imports from the producer (directly or through one intermediate module). Changes to the shared value will be visible through the import chain, and tools like IDEs can trace the dependency.

- **Unlinked files** share a string value by coincidence of matching literal values, with no import relationship connecting them. The contract is invisible to the dependency graph and will break silently if either side changes.

The `_files_are_linked` method checks both direct imports (`file_b in self.facts.imports_of(file_a)`) and one-hop imports (through an intermediate file). This limited depth is a pragmatic choice -- deeper chains are unlikely to represent intentional contracts.

For more on how `FactsDB` constructs import graphs and resolves import sources, see the [facts database documentation](facts-database-and-import-graphs.md).

## Why this matters

String contract violations occupy a dangerous blind spot in most development workflows:

- **They survive testing.** Unless a test specifically checks that two files agree on a string value, the violation is invisible. Integration tests may not cover all string contract paths.

- **They manifest at runtime.** A mismatched route name, config key, or event name typically causes a silent no-op or a confusing fallback behavior, not a crash.

- **They are invisible to type checkers.** Static analysis tools operate on types and imports. A string literal `"user_profile"` in one file and `"user_profiel"` in another are both valid strings -- no type checker flags the mismatch.

- **Fragile contracts are deferred bugs.** A fragile implicit contract works today because both sides happen to use the same string. The moment someone renames the value in one file without knowing about the other, a bug is introduced. The fragility finding identifies this risk *before* the rename happens.

## Design trade-offs

**Why ratio-based rather than binary?** A binary approach (flag all unmatched checked strings) would produce enormous numbers of false positives from files that interact with external APIs, databases, or protocols. The ratio-based approach recognizes that a file checking entirely external strings (ratio = 0) is fundamentally different from a file mixing internal contracts with potential violations (ratio > 0).

**Why focus on "identifier" kind strings?** User-facing strings (error messages, log text, UI labels) do not form cross-file contracts in the way that identifier strings do. An error message can change independently in two files without breaking anything. Filtering to `kind == "identifier"` focuses the analysis on strings that actually function as names, keys, or identifiers.

**Heuristic filtering trade-offs.** The checker applies several heuristic filters (`_should_ignore_checked_occurrence`) to exclude false positives: external origin detection via import analysis, file path sentinel detection, serialized key detection, external protocol detection, and duck-typing/config-access patterns (`.get()`, `getattr()`). Each filter reduces false positives but risks suppressing true positives. This aligns with Osoji's signal conservation principle -- each filter is evaluated for its impact on both false positive reduction and true positive preservation.

**Precision limitations.** Dynamic string construction (`f"route_{name}"`, `"prefix" + suffix`) defeats static analysis. The checker can only find violations involving literal string values that appear verbatim in the source code. Dynamically constructed strings form a class of implicit contracts that require runtime analysis to detect.
