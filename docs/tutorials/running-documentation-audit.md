# Running Your First Documentation Audit

This tutorial walks you through performing a complete Osoji audit, reading the
scorecard, understanding the multi-phase pipeline, and using the results to
improve your documentation and code quality.

**Time estimate**: 30-40 minutes.

**Prerequisites**:

- Osoji installed with an LLM API key configured.
- Shadow documentation already generated for your target project (see the
  *Generating Shadow Documentation* tutorial).
- A project with some documentation (README, docstrings, markdown guides).
  Imperfect docs make the tutorial more instructive.

---

## What does an audit measure?

An Osoji audit assesses your project across four pillars:

| Pillar | What it measures |
|--------|------------------|
| **Coverage** | What fraction of source files are documented by at least one doc file. |
| **Accuracy** | How many errors exist in your documentation (outdated references, wrong parameter names, contradictions with source code). |
| **Dead docs** | Documentation files that are process debris -- meeting notes, scratch pads, migration logs that don't serve any Diataxis purpose. |
| **Junk code** | Lines of source code that are dead, stale, or misleading (dead code, stale comments, misleading docstrings, commented-out blocks). |

The audit classifies every documentation file using the **Diataxis framework**,
which divides documentation into four types:

| Type | Purpose | Example |
|------|---------|---------|
| **Tutorial** | Learning-oriented, hands-on walkthrough | "Getting Started" guide |
| **How-to** | Task-oriented, goal-driven steps | "How to configure authentication" |
| **Reference** | Information-oriented, precise API docs | Function signatures, config options |
| **Explanatory** | Understanding-oriented, conceptual discussion | "Why we chose event sourcing" |

Files that don't fit any Diataxis category are flagged as **debris** -- errors
that should be deleted or reclassified.

---

## Step 1: Run a basic audit

Navigate to your project root and run:

```bash
osoji audit .
```

The audit executes in phases. Here is what you see in the terminal:

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
Osoji: Checking shadow documentation...
Osoji: Auto-updating 2 shadow doc(s)...
  [1/2] 50% [ok] helpers.py
  [2/2] 100% 3.1K^ 0.8Kv [ok] config.py
  [1/5] 20% [ok] README.md
  [2/5] 40% [ok] CONTRIBUTING.md
  [3/5] 60% [ok] docs/api-reference.md
  [4/5] 80% [DEBRIS] docs/meeting-notes.md
  [5/5] 100% 12.4K^ 3.2Kv [ok] CHANGELOG.md
Osoji: Building scorecard...
API tokens: 15,500^ 4,000v (19,500 total)
```

### Understanding the phases

The audit pipeline has the following phases:

#### Phase 1: Shadow doc check/fix (sequential)

```
Osoji: Checking shadow documentation...
Osoji: Auto-updating 2 shadow doc(s)...
```

Phase 1 ensures all shadow docs are up to date. It runs **sequentially**
because every later phase depends on having current shadow docs. By default,
the `--fix` flag is on, so stale shadow docs are automatically regenerated.

To skip auto-fixing:

```bash
osoji audit . --no-fix
```

In `--no-fix` mode, stale shadow docs are reported as warnings but not
regenerated. This is faster but may reduce accuracy of later phases.

#### Phases 2-4: Concurrent analysis

After Phase 1 completes, Phases 2 through 4 run **concurrently** via
`asyncio.gather`. A shared `RateLimiter` coordinates LLM calls across all
phases so token budgets are tracked globally and provider rate limits are
respected.

| Phase | Name | Type | What it does |
|-------|------|------|-------------|
| 2 | Doc analysis | LLM | Classifies each doc file by Diataxis type, matches it to relevant source files via shadow docs, validates accuracy with evidence quotes. |
| 3 | Debris verification | LLM | Loads code debris findings from `.osoji/findings/`, verifies `dead_code` and `latent_bug` findings against cross-file evidence from the facts database. False positives are suppressed. |
| 3.5 | Obligation checking | Pure Python | Checks for implicit string contracts across files (no LLM calls). Only runs when `--obligations` is passed. |
| 4 | Junk analysis | LLM + AST | Runs opt-in junk analyzers (dead code, dead params, dead plumbing, dead deps, dead CI/CD, orphaned files). Only runs when specific flags are passed. |

#### Phase 5: Scorecard building (sequential)

```
Osoji: Building scorecard...
```

Phase 5 aggregates results from all previous phases into a `Scorecard` data
structure. This is pure Python computation with no LLM calls. The scorecard
contains coverage metrics, accuracy counts, dead docs, and junk code
statistics.

#### Phase 5.5: Doc prompts (optional, sequential)

```
Osoji: Building concept inventory and writing prompts...
```

Phase 5.5 runs only when `--doc-prompts` is passed. It builds a concept
inventory from topic signatures, maps documentation coverage at the concept
level, and generates writing prompts for documentation gaps. This requires
the scorecard from Phase 5, so it runs after it.

### Verbose output

For detailed per-file progress and timing:

```bash
osoji --verbose audit .
```

This shows:

```
  [ok] README.md
  [ok] CONTRIBUTING.md
  [ok] docs/api-reference.md
  [DEBRIS] docs/meeting-notes.md
  [ok] CHANGELOG.md
  [phase 5.5 doc prompts: 8.3s] 18 concepts, 12 prompts
```

### Verification checkpoint

After your first audit:

1. The terminal shows a scorecard with coverage, accuracy, and junk metrics.
2. A `.osoji/analysis/` directory has been created with serialized results.
3. If any docs were classified as debris, they show with `[DEBRIS]` during
   Phase 2.

---

## Step 2: Reading the console report

The audit prints a Markdown report to stdout. Here is a realistic example
with some imperfections (to make it instructive):

```markdown
# Osoji Audit Failed

## Scorecard

Metric                       Value
---------------------------  -------------------------------------------
Source file coverage         67% (8/12 files)
Dead docs (debris)           2
Accuracy errors / live doc   0.50
Junk code fraction           3.2% (68 lines in 4 files)
Unactuated config            -- (not scanned)

### Doc linkage by type

*Fraction of docs of each type that link to at least one source file.*

Type          Linked  Total  %
------------  ------  -----  ---
explanatory   1       1      100%
how-to        2       3      67%
reference     2       3      67%
tutorial      1       1      100%

### Uncovered source files

- `src/utils/helpers.py` -- Internal utility functions
- `src/models/order.py` -- Order data model
- `src/config.py` -- Application configuration
- `src/middleware/auth.py` -- Authentication middleware

### Dead documentation

- `docs/meeting-notes.md`
- `docs/migration-plan-2025.md`

### Accuracy errors by category

Category                Count
----------------------  -----
outdated_reference      2
wrong_parameter_name    1

### Junk code by category

Category        Items  Lines
--------------  -----  -----
dead_code       3      38
stale_comment   2      18
commented_out   1      12

### Worst files by junk fraction

File                  Junk %  Junk lines / Total
--------------------  ------  -------------------
src/legacy/old_api.py  15%     22/145
src/utils/helpers.py    5%     12/240

*Phases not run: `--dead-code`, `--dead-params`, `--dead-plumbing`,
`--dead-deps`, `--dead-cicd`, `--orphaned-files`. Re-run with those flags
for a complete scorecard.*

## Errors (blocking)

### `docs/meeting-notes.md`
**Category**: debris
**Issue**: Documentation debris: Process artifact (meeting notes)
**Remediation**: Delete this file

### `docs/migration-plan-2025.md`
**Category**: debris
**Issue**: Documentation debris: Completed migration plan
**Remediation**: Delete this file

### `docs/api-reference.md`
**Category**: doc_outdated_reference
**Issue**: References `UserManager.create()` which was renamed to
`UserManager.register()` [evidence: src/models/user.py.shadow.md --
"create_user was renamed to register_user in commit abc123"]
**Remediation**: Update the reference to use the current function name

## Warnings (non-blocking)

- `src/api/routes.py`: L42-48: stale_comment -- comment references
  removed field `user.password_hash`
- `src/legacy/old_api.py`: L12-33: dead_code -- function
  `legacy_handler` is never called

---
**Result**: 3 error(s), 2 warning(s), 0 info(s)
```

### Understanding each section

#### Scorecard summary

The top-level table shows headline metrics:

| Metric | What it means |
|--------|---------------|
| **Source file coverage** | Percentage of source files that at least one documentation file references or covers. 67% means 8 of 12 source files are mentioned in docs. |
| **Dead docs (debris)** | Number of documentation files classified as process debris (not serving a Diataxis purpose). These are errors. |
| **Accuracy errors / live doc** | Average number of accuracy errors per live (non-debris) documentation file. Lower is better. |
| **Junk code fraction** | Percentage of total source lines that are junk (dead code, stale comments, etc.). |
| **Unactuated config** | Shows "-- (not scanned)" unless `--dead-plumbing` was passed. |

#### Doc linkage by type

Shows what fraction of docs of each Diataxis type successfully link to source
files via shadow docs. A low percentage suggests docs may be too generic or
reference outdated code paths.

#### Uncovered source files

Lists source files that no documentation file references. These are gaps in
your documentation coverage. The purpose description comes from the topic
signature generated during shadow doc creation.

#### Dead documentation

Lists docs classified as debris. These are errors -- the audit fails if any
debris is found. Common debris types include meeting notes, scratch pads,
completed migration plans, and abandoned drafts.

#### Accuracy errors by category

Breaks down documentation errors by type. Common categories:

- `outdated_reference` -- Doc references a renamed/removed function or class.
- `wrong_parameter_name` -- Doc lists a parameter that no longer exists.
- `contradicts_implementation` -- Doc describes behavior that differs from code.
- `missing_parameter` -- Doc omits a parameter that exists in the code.

#### Junk code by category

Breaks down code debris by type:

- `dead_code` -- Unused functions, unreachable branches.
- `stale_comment` -- Comments that contradict the current code.
- `commented_out` -- Commented-out code blocks (3+ lines).
- `misleading_docstring` -- Docstrings that don't match the implementation.

#### Worst files by junk fraction

The top files by percentage of lines that are junk. Files above 5% junk
fraction are highlighted.

#### Errors and Warnings

- **Errors** are blocking -- the audit exits with code 1.
- **Warnings** are informational -- the audit still passes.

Each error includes:
- The file path.
- The category.
- A description of the issue.
- A remediation suggestion.

For accuracy errors, the evidence trail shows which shadow doc was used and
what quote supports the finding.

---

## Step 3: Generate an HTML report

The HTML report provides the same information in an interactive, styled format
suitable for sharing with teammates:

```bash
osoji audit . --format html
```

Output:

```
Report written to .osoji/analysis/report.html
```

Open the file in a browser:

```bash
# macOS
open .osoji/analysis/report.html

# Linux
xdg-open .osoji/analysis/report.html

# Windows
start .osoji/analysis/report.html
```

The HTML report features:

- A styled scorecard with all metrics from the console report.
- Color-coded severity indicators (errors in red, warnings in amber).
- Collapsible sections for large finding lists.
- Light and dark theme support.
- A hanko (Japanese seal) branding element.

You can also generate the HTML report from a cached audit result without
re-running the audit:

```bash
osoji report . --format html
```

### Verification checkpoint

1. The `.osoji/analysis/report.html` file exists.
2. Opening it in a browser shows a styled report with the same metrics as the
   console output.

---

## Step 4: Generate a JSON report

For CI/CD integration and programmatic consumption, generate a JSON report:

```bash
osoji audit . --format json
```

This prints structured JSON to stdout. Redirect it to a file:

```bash
osoji audit . --format json > audit-results.json
```

Or use the `report` command for a cached result:

```bash
osoji report . --format json > audit-results.json
```

The JSON structure:

```json
{
  "passed": false,
  "errors": 3,
  "warnings": 2,
  "infos": 0,
  "issues": [
    {
      "path": "docs/meeting-notes.md",
      "severity": "error",
      "category": "debris",
      "message": "Documentation debris: Process artifact (meeting notes)",
      "remediation": "Delete this file",
      "line_start": null,
      "line_end": null,
      "origin": {
        "source": "llm",
        "plugin": "doc_analysis"
      }
    },
    {
      "path": "src/api/routes.py",
      "severity": "warning",
      "category": "stale_comment",
      "message": "L42-48: comment references removed field `user.password_hash`",
      "remediation": "Update or remove the comment",
      "line_start": 42,
      "line_end": 48,
      "origin": {
        "source": "llm",
        "plugin": "code_debris"
      }
    }
  ],
  "config": {
    "provider": "anthropic",
    "model_medium": "claude-sonnet-4-20250514"
  },
  "scorecard": {
    "coverage_pct": 66.7,
    "covered_count": 8,
    "total_source_count": 12,
    "dead_docs": ["docs/meeting-notes.md", "docs/migration-plan-2025.md"],
    "total_accuracy_errors": 3,
    "live_doc_count": 6,
    "accuracy_errors_per_doc": 0.5,
    "junk_total_lines": 68,
    "junk_total_source_lines": 2120,
    "junk_fraction": 0.032,
    "junk_item_count": 6,
    "junk_file_count": 4,
    "coverage_by_type": {
      "explanatory": 100.0,
      "how-to": 66.7,
      "reference": 66.7,
      "tutorial": 100.0
    }
  }
}
```

Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `passed` | boolean | `true` if no errors (warnings don't fail the audit). |
| `errors` | integer | Count of error-severity issues. |
| `warnings` | integer | Count of warning-severity issues. |
| `issues` | array | All findings with path, severity, category, message, remediation, line range, and origin. |
| `scorecard` | object | Full scorecard with all metrics and per-file entries. |
| `config` | object | Snapshot of resolved configuration used for this audit run. |

The `origin` field on each issue tells you how the finding was produced:

| Source | Meaning |
|--------|---------|
| `llm` | Found via LLM analysis. |
| `static` | Found via static analysis (AST parsing). |
| `hybrid` | Found via combined static + LLM analysis. |

The `plugin` field identifies which analysis module produced the finding
(e.g., `doc_analysis`, `code_debris`, `obligations`).

---

## Step 5: Understanding the scorecard in depth

The scorecard is built by the `build_scorecard()` function in
`src/osoji/scorecard.py`. It aggregates results from all audit phases into
structured data types.

### `CoverageEntry`

Each source file gets a `CoverageEntry`:

```python
@dataclass
class CoverageEntry:
    source_path: str
    topic_signature: dict | None
    covering_docs: list[dict]  # [{"path": str, "classification": str}]
```

- `source_path`: The relative path to the source file.
- `topic_signature`: The file's topic signature (purpose + key topics), used
  to display purpose in the "Uncovered source files" section.
- `covering_docs`: List of documentation files that reference this source
  file, with their Diataxis classification.

A source file is "covered" if `covering_docs` is non-empty.

### `JunkCodeEntry`

Each source file with junk findings gets a `JunkCodeEntry`:

```python
@dataclass
class JunkCodeEntry:
    source_path: str
    total_lines: int
    junk_lines: int
    junk_fraction: float
    items: list[dict]
```

- `source_path`: The relative path to the source file.
- `total_lines`: Total lines in the source file.
- `junk_lines`: Lines identified as junk (after merging overlapping ranges).
- `junk_fraction`: `junk_lines / total_lines`.
- `items`: Individual junk findings with category, line range, and source.

The overall `junk_fraction` on the scorecard is computed as
`junk_total_lines / junk_total_source_lines` across all source files, not
just files with findings.

### Junk line counting

Junk lines are counted using merged ranges. If two findings overlap (e.g.,
a dead function at L10-30 and a stale comment at L25-28), the overlapping
lines are counted only once. The `merge_ranges()` function in
`scorecard.py` handles this.

---

## Step 6: Opt-in audit phases

The base audit always runs documentation classification, accuracy validation,
and code debris detection. You can enable additional analysis with flags:

### Dead code detection (`--dead-code`)

```bash
osoji audit . --dead-code
```

Scans for unused symbols across the entire codebase. Uses AST plugins for
ground truth on imports/exports and LLM verification for ambiguous candidates.

### Dead parameter detection (`--dead-params`)

```bash
osoji audit . --dead-params
```

Analyzes function parameters to find those that are declared but never used
at any call site.

### Dead plumbing detection (`--dead-plumbing`)

```bash
osoji audit . --dead-plumbing
```

Detects unactuated configuration obligations -- config schema fields that are
defined but never read or used at runtime.

### Dead dependency detection (`--dead-deps`)

```bash
osoji audit . --dead-deps
```

Identifies package dependencies declared in manifest files (pyproject.toml,
package.json, etc.) that are never imported by any source file.

### Dead CI/CD detection (`--dead-cicd`)

```bash
osoji audit . --dead-cicd
```

Finds stale CI/CD pipeline elements -- unused jobs, targets, or stages in
workflow files.

### Orphaned file detection (`--orphaned-files`)

```bash
osoji audit . --orphaned-files
```

Detects source files that are unreachable from any entry point via the
purpose graph.

### All junk phases (`--junk`)

```bash
osoji audit . --junk
```

Equivalent to passing all of the above flags at once.

### Obligation checking (`--obligations`)

```bash
osoji audit . --obligations
```

Checks for implicit string contracts across files. This is pure Python with
no LLM calls. When two files share the same string literal used as a key or
identifier, renaming in one silently breaks the other at runtime.

### Full audit (`--full`)

```bash
osoji audit . --full
```

Equivalent to `--junk --obligations --doc-prompts`. Runs every optional phase.

### Obligation checking (`--obligations`)

Obligation checking deserves special attention because it produces a different
kind of finding: **implicit string contracts**.

When two files share the same string literal used as a key, identifier, or
discriminant tag, they form an implicit contract. Renaming the string in one
file silently breaks the other at runtime (a value-level error). If the files
instead imported a shared constant, renaming would cause an `ImportError` or
`NameError` at load time (a name-level error), which is immediately visible.

```bash
osoji audit . --obligations
```

Obligation findings appear in the "Implicit String Contracts" section of the
report:

```
## Implicit String Contracts

These findings identify string literals shared between source and test files.
They represent coupling that is often unintentional...

- `src/api/routes.py`: String "user_created" shared with `src/events/handler.py` (2 occurrences)
- `src/config.py`: String "database_url" shared with `tests/test_config.py` (3 occurrences)
```

These are informational (severity `info`). They do not fail the audit. The
remediation is to extract shared strings into constants so that renaming
produces loud compile-time or import-time errors instead of silent runtime
failures.

### Overriding findings

If the audit produces false positives, you can override them with project-
specific rules. Create a `.osoji/rules` file with plain-text rules:

```
Keep CLAUDE_CODE_PROMPT.md as historical reference.
Files in docs/internal/ are team documentation, not debris.
```

These rules are loaded by the audit pipeline and applied during debris
classification. Rules use natural language -- the LLM interprets them.

---

## Step 7: Understanding the analysis directory

After each audit run, Osoji writes serialized results to `.osoji/analysis/`.
This directory is cleaned and recreated on every run.

### Per-doc analysis files

Each documentation file analyzed in Phase 2 gets a JSON result at
`.osoji/analysis/docs/<doc-path>.json`:

```json
{
  "path": "docs/api-reference.md",
  "classification": "reference",
  "confidence": 0.95,
  "classification_reason": "API documentation with function signatures and parameter descriptions",
  "matched_shadows": [
    "src/models/user.py",
    "src/api/routes.py"
  ],
  "findings": [
    {
      "category": "outdated_reference",
      "severity": "error",
      "description": "References UserManager.create() which was renamed to register()",
      "shadow_ref": "src/models/user.py.shadow.md",
      "evidence": "The create_user function was renamed to register_user",
      "remediation": "Update the reference to use the current function name"
    }
  ],
  "is_debris": false,
  "topic_signature": {
    "purpose": "API reference for user management endpoints",
    "topics": ["user API", "CRUD operations", "authentication"]
  }
}
```

Key fields:

| Field | Description |
|-------|-------------|
| `classification` | Diataxis type: `tutorial`, `how-to`, `reference`, `explanatory`, or `debris`. |
| `confidence` | LLM's confidence in the classification (0.0-1.0). |
| `matched_shadows` | Source files that this doc references or covers. |
| `findings` | Accuracy errors with evidence trails back to shadow docs. |
| `is_debris` | `true` if classified as process artifact. |

### Per-analyzer junk files

Each junk analyzer writes results grouped by source file at
`.osoji/analysis/junk/<analyzer>/<source-path>.json`.

### Scorecard file

The aggregated scorecard is written to `.osoji/analysis/scorecard.json`. This
is the same data that `osoji report` reads.

---

## Step 8: Acting on findings

The audit report tells you what to fix. Here is a systematic approach.

### Fix documentation gaps (coverage)

The "Uncovered source files" section lists files without documentation
coverage. For each:

1. Determine if the file is user-facing or internal.
2. If user-facing, write documentation that references it. Use the topic
   signature to understand what to document.
3. If internal, consider whether a reference doc or code comment suffices.

For a systematic approach, use the `--doc-prompts` flag to generate targeted
writing prompts (see the *Using Doc Prompts* tutorial).

### Fix accuracy errors

Each accuracy error includes an evidence trail. For example:

```
**Issue**: References `UserManager.create()` which was renamed to
`UserManager.register()` [evidence: src/models/user.py.shadow.md --
"create_user was renamed to register_user"]
```

Open the documentation file, find the outdated reference, and update it.

### Remove dead documentation (debris)

Files classified as debris should be deleted:

```bash
git rm docs/meeting-notes.md
git rm docs/migration-plan-2025.md
```

If a file is incorrectly classified as debris, add a rule to `.osoji/rules`.

### Clean up junk code

For each junk finding:

- **Dead code**: Remove unused functions or unreachable branches.
- **Stale comments**: Update or remove comments that contradict the code.
- **Commented-out code**: Remove old code blocks. They live in git history.
- **Misleading docstrings**: Update docstrings to match the implementation.

---

## Step 9: Re-run after fixes

After making fixes, re-run the audit to verify improvements:

```bash
osoji audit .
```

### Example: removing debris

Suppose you deleted two debris files and updated one outdated reference.
The new report shows:

```
# Osoji Audit Passed

## Scorecard

Metric                       Value
---------------------------  -------------------------------------------
Source file coverage         67% (8/12 files)
Dead docs (debris)           0
Accuracy errors / live doc   0.17
Junk code fraction           3.2% (68 lines in 4 files)
Unactuated config            -- (not scanned)

...

---
**Result**: 0 error(s), 2 warning(s), 0 info(s)
```

Key changes:

- Dead docs dropped from 2 to 0.
- Accuracy errors dropped from 0.50 to 0.17 per doc.
- The audit now **passes** (0 errors).

Note that warnings (stale comments, dead code) do not fail the audit. They
are informational. You can address them over time.

### Verification checkpoint

1. The audit passes (exit code 0, report shows "Osoji Audit Passed").
2. Dead docs count is 0.
3. Accuracy error count has decreased.

---

## Step 10: Using the `osoji report` command

After any audit run, the result is cached in `.osoji/analysis/`. You can
re-render the same result in different formats without re-running the audit
(no LLM calls):

```bash
# Text format (default)
osoji report .

# JSON format
osoji report . --format json

# HTML format
osoji report . --format html
```

If no cached result exists, the command fails with a clear error:

```
Error: No cached audit result. Run 'osoji audit' first.
```

This is useful for:

- Generating an HTML report after a text-mode audit.
- Extracting JSON for CI without re-running expensive LLM calls.
- Sharing results with teammates in different formats.

---

## Wrap-up

You have learned the complete audit workflow:

1. **Generate shadows** -- Run `osoji shadow .` to create the ground truth.
2. **Run the audit** -- `osoji audit .` to assess coverage, accuracy, dead
   docs, and junk code.
3. **Read the scorecard** -- Understand coverage percentages, accuracy
   errors per doc, dead doc counts, and junk fractions.
4. **Generate reports** -- HTML for sharing, JSON for CI.
5. **Fix issues** -- Delete debris, update outdated references, remove junk.
6. **Re-audit** -- Verify improvements.

### Key concepts

- The audit pipeline runs in phases (1 through 5.5).
- Phase 1 is sequential (shadow doc prerequisite).
- Phases 2-4 run concurrently with a shared rate limiter.
- Phase 5 builds the scorecard (pure Python).
- Phase 5.5 generates doc prompts (optional, requires `--doc-prompts`).
- Exit code 0 means passed (no errors), exit code 1 means failed (errors
  found).
- Warnings do not cause failure.

### Next steps

- **Using Doc Prompts to Fill Documentation Gaps** (tutorial) -- Generate
  writing prompts for coverage gaps.
- **Protecting Your Repository with Safety Checks** (tutorial) -- Set up
  pre-commit safety scanning.
