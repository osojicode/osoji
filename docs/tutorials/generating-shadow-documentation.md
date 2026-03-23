# Generating Your First Shadow Documentation

This tutorial teaches you what shadow documentation is, how to generate it,
how to read the output, and how to keep it up to date as your codebase
evolves.

**Time estimate**: 20-30 minutes.

**Prerequisites**:

- Osoji installed and configured with an LLM API key (see the
  *Getting Started with the CLI* tutorial).
- A project repository with at least 5-10 source files.
- Basic familiarity with the `osoji` CLI.

---

## What are shadow docs?

Shadow documentation is a layer of LLM-generated summaries that sit alongside
your source code. For every source file Osoji processes, it creates a
`.shadow.md` sidecar file that captures:

- The file's **purpose and architecture** in a few paragraphs.
- **Key classes, functions, and constants** with line number references.
- **Dependencies** -- what the file imports and what imports it.
- **Findings** -- code quality issues discovered during analysis (stale
  comments, dead code, misleading docstrings).

These summaries are stored under `.osoji/shadow/`, mirroring your source tree.
They serve two main purposes:

1. **Fast context for AI agents.** Instead of parsing an entire source file
   (hundreds or thousands of tokens), an agent can read the shadow doc (tens of
   tokens) and get the same structural understanding. This is the compression
   that `osoji stats` measures.

2. **Audit foundation.** The documentation audit pipeline uses shadow docs as
   ground truth to validate your human-written documentation for accuracy and
   coverage.

Shadow docs are ephemeral artifacts owned by Osoji. You can regenerate them at
any time. They should be committed to your repository (they are not in
`.gitignore`) so that AI agents and teammates can read them without re-running
generation.

---

## Step 1: Preview with dry run

Before spending LLM tokens, see what Osoji would process:

```bash
osoji shadow --dry-run .
```

Sample output:

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
Dry run for: /home/dev/myproject

Impl hash: a1b2c3d4e5f67890
Total source files: 15
  Would generate: 15
  Already cached:  0
Directories: 4

Estimated tokens (for 15 file(s) to generate):
  Input:  ~18,200
  Output: ~4,730
Estimated cost: ~$0.13
```

### Understanding the output

| Field | Meaning |
|-------|---------|
| **Impl hash** | Composite hash of Osoji's own implementation files. Changes when Osoji is updated. |
| **Total source files** | Files discovered by the walker (respects `.gitignore` by default). |
| **Would generate** | Files that need generation -- either missing or stale shadow docs. |
| **Already cached** | Files whose shadow docs are up to date (source hash and impl hash both match). |
| **Directories** | Number of directories that will get roll-up summaries. |
| **Estimated tokens/cost** | Rough estimates based on file sizes (~4 characters/token). |

### File discovery

Osoji discovers files using `git ls-files` when inside a git repository, or a
filesystem walk as a fallback. By default it respects `.gitignore` -- files
ignored by git are also ignored by Osoji. Use `--no-gitignore` to override:

```bash
osoji shadow --dry-run --no-gitignore .
```

Osoji processes files with these extensions by default: `.py`, `.js`, `.ts`,
`.jsx`, `.tsx`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.hpp`, `.cs`,
`.rb`, `.php`, `.swift`, `.kt`, `.scala`, and more. Directories like
`.git`, `node_modules`, `__pycache__`, `venv`, `build`, `dist`, and `.osoji`
itself are always skipped.

### Verbose dry run

For a per-file listing showing staleness reasons and file sizes:

```bash
osoji --verbose shadow --dry-run .
```

Output:

```
...
Files to process (15):
  [missing] src/models/user.py  (2,340 bytes)
  [missing] src/models/order.py  (1,890 bytes)
  [stale]   src/api/routes.py  (3,120 bytes)
  [stale-impl] src/utils/helpers.py  (980 bytes)
  ...

Cached (0):
```

The staleness reasons are:

| Reason | Meaning |
|--------|---------|
| `missing` | No shadow doc exists for this source file. |
| `stale` | The source file has changed since the shadow doc was generated. |
| `stale-impl` | The source file has not changed, but Osoji's own generation toolchain has been updated. |

---

## Step 2: Generate shadow documentation

Run the full generation:

```bash
osoji shadow .
```

Output:

```
Config: provider=anthropic model=medium:claude-sonnet-4-20250514 (built-in default)
  [1/15] 7% [ok] user.py
  [2/15] 13% [ok] order.py
  [3/15] 20% [ok] product.py
  ...
  [15/15] 100% 18.2K^ 4.7Kv [ok] config.py
```

Each line shows:

- Progress counter (`[N/total]`) and percentage.
- Cumulative token usage (`18.2K^` = input tokens, `4.7Kv` = output tokens).
- Status: `[ok]` for success, `[DEBRIS]` if code debris was found, `[skip]` if
  cached, `[ERROR]` on failure.
- The file name.

Use `--verbose` for full relative paths on separate lines:

```bash
osoji --verbose shadow .
```

Output:

```
  [ok] src/models/user.py
  [ok] src/models/order.py
  [DEBRIS] src/api/routes.py
  ...
```

### What gets created

After generation, your project root contains a `.osoji/` directory with this
structure:

```
.osoji/
  shadow/
    src/
      models/
        user.py.shadow.md          # Per-file shadow doc
        order.py.shadow.md
        product.py.shadow.md
        _directory.shadow.md       # Directory roll-up
      api/
        routes.py.shadow.md
        middleware.py.shadow.md
        _directory.shadow.md
      utils/
        helpers.py.shadow.md
        _directory.shadow.md
    _root.shadow.md                # Project root roll-up
  facts/
    src/
      models/
        user.py.facts.json         # Imports, exports, calls, string literals
        order.py.facts.json
        ...
  symbols/
    src/
      models/
        user.py.symbols.json       # Functions, classes, constants
        ...
  findings/
    src/
      api/
        routes.py.findings.json    # Code debris findings
        ...
  signatures/
    src/
      models/
        user.py.signature.json     # Topic signature for coverage analysis
        ...
```

Each source file produces up to five sidecar files:

| Sidecar | Extension | Purpose |
|---------|-----------|---------|
| Shadow doc | `.shadow.md` | Human/AI-readable summary |
| Facts | `.facts.json` | Structured metadata: imports, exports, calls, string literals |
| Symbols | `.symbols.json` | Function/class/constant definitions with line ranges |
| Findings | `.findings.json` | Code debris found during analysis |
| Signature | `.signature.json` | Topic signature for documentation coverage |

### Verification checkpoint

Confirm the following:

1. `.osoji/shadow/` exists and contains `.shadow.md` files mirroring your
   source tree.
2. At least one `_directory.shadow.md` file exists.
3. `_root.shadow.md` exists at `.osoji/shadow/`.
4. `.osoji/facts/` contains `.facts.json` files.
5. `.osoji/symbols/` contains `.symbols.json` files.

---

## Step 3: Reading a shadow doc

Open any generated shadow doc to understand its structure. Here is a
representative example:

```
# src/models/user.py
@source-hash: 3a7f1c2e9b4d8e01
@impl-hash: c5d6e7f8a9b0c1d2
@generated: 2026-03-21T14:32:05Z

## Purpose

Defines the `User` data model and associated validation logic. This module
is the canonical representation of users throughout the application and
is imported by the API routes, authentication middleware, and admin dashboard.

## Key Components

- **`User` class (L12-58)**: Dataclass representing a user with fields for
  `id`, `email`, `name`, `role`, and `created_at`. Includes a `validate()`
  method (L34-52) that enforces email format and role constraints.

- **`UserRole` enum (L5-9)**: Defines valid roles: `admin`, `editor`,
  `viewer`.

- **`create_user()` function (L61-85)**: Factory function that validates
  input, hashes the password, and returns a new `User` instance.

## Dependencies

- Imports: `dataclasses`, `enum`, `re`, `hashlib`
- Imported by: `src/api/routes.py`, `src/auth/middleware.py`

## Findings

- **stale_comment (L22, warning)**: Comment says "password is stored in
  plain text" but the implementation hashes it with SHA-256.
```

### Anatomy of the header

The first four lines form the header:

```
# src/models/user.py
@source-hash: 3a7f1c2e9b4d8e01
@impl-hash: c5d6e7f8a9b0c1d2
@generated: 2026-03-21T14:32:05Z
```

| Field | Description |
|-------|-------------|
| `@source-hash` | SHA-256 of the source file's content, truncated to 16 hex characters. Used to detect when the source has changed. |
| `@impl-hash` | Composite hash of Osoji's own implementation files (everything under `src/osoji/` that affects generation output). Used to detect when the generation toolchain has changed. |
| `@generated` | UTC timestamp of when this shadow doc was generated. |

The hashing is performed by the `hasher` module:

- `compute_hash()` computes SHA-256 of a string and returns the first 16 hex
  characters.
- `compute_file_hash()` handles binary detection and encoding before hashing.
- `compute_impl_hash()` hashes all implementation files, excluding those that
  don't affect output (like `cli.py`, `hooks.py`, `observatory.py`, `stats.py`, and the `safety/` subpackage).

### Body sections

The body after the blank line following the header is the documentation
content. While the exact structure varies by file, you will typically see:

- **Purpose** -- A brief description of what the file does and its role in the
  project.
- **Key Components** -- Functions, classes, and constants with line number
  references (e.g., `L12-58`).
- **Dependencies** -- What the file imports and what other files import it.
- **Findings** -- Code quality issues categorized as `dead_code`,
  `stale_comment`, `misleading_docstring`, `commented_out_code`, or
  `latent_bug`, each with a severity of `error` or `warning`.

---

## Step 4: Understanding staleness and caching

Osoji uses hash-based caching to avoid regenerating shadow docs unnecessarily.
The caching logic works as follows:

1. When Osoji generates a shadow doc, it records the source file's hash
   (`@source-hash`) and the implementation hash (`@impl-hash`) in the header.

2. On the next run, Osoji reads the existing shadow doc's header and compares:
   - The current source file hash against `@source-hash`.
   - The current implementation hash against `@impl-hash`.

3. If **both** match, the shadow doc is up to date and is skipped.

4. If the **source hash** differs, the file is marked `stale` and
   regenerated.

5. If the source hash matches but the **impl hash** differs (or is absent --
   old-format doc), the file is marked `stale-impl` and regenerated.

### Demonstrating staleness

Make a small change to one of your source files:

```bash
echo "# Added a comment" >> src/models/user.py
```

Now run the dry run again:

```bash
osoji shadow --dry-run .
```

Output:

```
Total source files: 15
  Would generate: 1
  Already cached:  14
```

Only the modified file needs regeneration. Run the full generation:

```bash
osoji shadow .
```

Output:

```
  [1/1] 100% 2.3K^ 0.6Kv [ok] user.py
```

Only the changed file was processed. Everything else was cached.

### Checking staleness without generating

The `osoji check` command reports staleness without making LLM calls:

```bash
osoji check .
```

If everything is up to date:

```
All shadow documentation is up to date.
```

If there are stale docs:

```
Found 1 file(s) with issues:

  [stale] src/models/user.py

Marked 1 shadow doc(s) with stale warnings.
Manifest written to .osoji/staleness.json
Run 'osoji shadow .' to regenerate.
```

For a read-only report (no file modifications):

```bash
osoji check --dry-run .
```

This prints the same report but does not inject stale warnings into shadow
docs or write the staleness manifest.

### Stale warning injection

When `osoji check .` runs (without `--dry-run`), it does two things:

1. **Injects a warning line** into stale shadow docs:

   ```
   > ⚠ STALE — source content has changed since this doc was generated
   ```

   or for impl staleness:

   ```
   > ⚠ STALE — generation toolchain has changed since this doc was generated
   ```

2. **Writes a staleness manifest** to `.osoji/staleness.json`:

   ```json
   {
     "generated": "2026-03-21T15:00:00Z",
     "stale": [
       {"path": "src/models/user.py", "reason": "stale"}
     ]
   }
   ```

These warnings are automatically stripped when shadow docs are regenerated.

### Verification checkpoint

1. Modify a source file and run `osoji shadow --dry-run .`. Confirm only the
   modified file shows as "Would generate."
2. Run `osoji shadow .` and confirm only the modified file is processed.
3. Undo the modification and run `osoji shadow --dry-run .` again. Confirm
   everything is cached.

---

## Step 5: Large file chunking

When a source file exceeds approximately 150,000 input tokens (very large
files), Osoji automatically splits it into chunks for LLM processing. Each
chunk targets about 120,000 tokens with a 5% overlap at boundaries to ensure
continuity.

You do not need to configure chunking. It happens transparently. The
user-visible difference is that large files may take longer to process and
consume more tokens. The resulting shadow doc is assembled from all chunk
responses.

For most projects, files are small enough that chunking never triggers.

---

## Step 6: Directory roll-ups

In addition to per-file shadow docs, Osoji generates directory-level summaries
that aggregate the shadow docs of all files in a directory.

### Per-directory summaries: `_directory.shadow.md`

Each directory with source files gets a `_directory.shadow.md` file. Open one:

```
# src/models/
@children-hash: 8f2a3b4c5d6e7f01
@impl-hash: c5d6e7f8a9b0c1d2
@generated: 2026-03-21T14:32:10Z

## Purpose

The models directory defines the core data models for the application:
User, Order, and Product. These dataclasses are the canonical representations
used throughout the codebase.

## Components

- **user.py**: User data model with validation and role management.
- **order.py**: Order data model with line items and status tracking.
- **product.py**: Product catalog entry with pricing and inventory.

## Cross-cutting concerns

All models use Python dataclasses and share a common validation pattern
through the `validate()` method convention.
```

Notice the `@children-hash` field instead of `@source-hash`. This is a
Merkle-style hash computed from the sorted `(name, content_hash)` pairs of
all children (files and subdirectories). A change to any file in the subtree
changes the children hash, triggering re-generation of the roll-up.

### Project root summary: `_root.shadow.md`

The root-level roll-up is at `.osoji/shadow/_root.shadow.md`. It synthesizes
the shadow docs of all top-level files and directory summaries into a project
overview. This is the best starting point for an AI agent trying to understand
your project.

### Roll-up generation order

Osoji processes the codebase **bottom-up**:

1. Files in the deepest directories are processed first.
2. Once all files in a directory are done, the directory roll-up is generated.
3. This continues upward until the root roll-up is generated.

This ensures each directory summary has the full context of its children.

---

## Step 7: Plugin-based fact extraction

Alongside shadow doc generation, Osoji extracts structured facts from source
files. Facts are stored in `.facts.json` files and include:

- **Imports**: What the file imports (source specifier, imported names).
- **Exports**: Public API surface (things importable by other files).
- **Calls**: Significant cross-file function/method calls.
- **Member writes**: Writes to object/class fields.
- **String literals**: String constants that participate in cross-file contracts.

For Python and TypeScript files, Osoji has language-specific AST plugins that
extract ground-truth structural data (like imports and exports) directly from
the syntax tree. These AST-extracted facts are merged with LLM-extracted
semantic data.

You can identify AST-extracted facts by the `extraction_method: "ast"` field
in the facts file:

```json
{
  "path": "src/models/user.py",
  "imports": [
    {
      "source": "dataclasses",
      "names": ["dataclass", "field"],
      "extraction_method": "ast"
    }
  ],
  "exports": [
    {
      "name": "User",
      "kind": "class",
      "extraction_method": "ast"
    }
  ],
  "string_literals": [
    {
      "value": "admin",
      "line": 7,
      "kind": "identifier",
      "usage": "defined"
    }
  ]
}
```

The `FactsDB` class (in `src/osoji/facts.py`) loads these files and provides
query methods for import graphs, export analysis, and string contract checking.
This is used internally by the audit pipeline for cross-file verification of
findings.

---

## Step 8: Symbol extraction

Every source file also gets a `.symbols.json` sidecar in `.osoji/symbols/`.
This contains structured metadata about all functions, classes, constants, and
module-level variables defined in the file:

```json
[
  {
    "name": "User",
    "kind": "class",
    "line_start": 12,
    "line_end": 58,
    "visibility": "public",
    "parameters": []
  },
  {
    "name": "create_user",
    "kind": "function",
    "line_start": 61,
    "line_end": 85,
    "visibility": "public",
    "parameters": [
      {"name": "email", "optional": false},
      {"name": "name", "optional": false},
      {"name": "role", "optional": true}
    ]
  },
  {
    "name": "_hash_password",
    "kind": "function",
    "line_start": 88,
    "line_end": 95,
    "visibility": "internal"
  }
]
```

Symbols are classified as `public` (importable/exported) or `internal`
(private helpers, underscore-prefixed). The symbols database is used by the
audit pipeline for dead code detection and dead parameter analysis.

---

## Step 9: Orphan cleanup

When you delete or rename a source file, the corresponding shadow doc,
facts file, symbols file, findings file, and signature file become orphaned.
Osoji cleans these up automatically during the next shadow generation run.

### Demonstrating orphan cleanup

Suppose you have a file `src/utils/deprecated.py` with a corresponding
shadow doc at `.osoji/shadow/src/utils/deprecated.py.shadow.md`.

Delete or rename the source file:

```bash
git rm src/utils/deprecated.py
```

Run shadow generation:

```bash
osoji shadow .
```

After completion, verify that the orphaned sidecar files have been removed:

```bash
ls .osoji/shadow/src/utils/deprecated.py.shadow.md
# ls: cannot access '.osoji/shadow/src/utils/deprecated.py.shadow.md': No such file or directory
```

The orphan cleanup is performed automatically. No separate command is needed.

### Verification checkpoint

1. Delete or rename a source file.
2. Run `osoji shadow .`.
3. Confirm the corresponding `.shadow.md` file in `.osoji/shadow/` has been
   removed.
4. Confirm that the directory roll-up (`_directory.shadow.md`) has been
   updated to reflect the removal.

---

## Step 10: Understanding findings

During shadow generation, the LLM identifies code quality issues and stores
them as "findings" in `.osoji/findings/`. These are not just informational --
they feed into the audit pipeline's Phase 3 (debris verification).

### Finding categories

Each finding has a category, severity, and description:

| Category | Severity | Description |
|----------|----------|-------------|
| `dead_code` | warning | Unused functions, unreachable branches, dead variables. |
| `stale_comment` | warning | Comments that contradict the current implementation. |
| `misleading_docstring` | warning | Docstrings that don't match the code. |
| `commented_out_code` | warning | Blocks of commented-out code (3+ lines). |
| `latent_bug` | error | Code that will crash or produce wrong results at runtime. |

### Reading a findings file

Open a `.findings.json` file to see the raw findings:

```json
{
  "source": "src/api/routes.py",
  "source_hash": "3a7f1c2e9b4d8e01",
  "impl_hash": "c5d6e7f8a9b0c1d2",
  "findings": [
    {
      "category": "stale_comment",
      "line_start": 42,
      "line_end": 44,
      "severity": "warning",
      "description": "Comment says 'password is stored in plain text' but the implementation hashes it with SHA-256",
      "suggestion": "Update the comment to reflect the current hashing implementation",
      "cross_file_verification_needed": false
    },
    {
      "category": "dead_code",
      "line_start": 88,
      "line_end": 102,
      "severity": "warning",
      "description": "Function `legacy_handler` is defined but never called within this file",
      "suggestion": "If this function is not called from other files, remove it",
      "cross_file_verification_needed": true
    }
  ]
}
```

### Cross-file verification

When `cross_file_verification_needed` is `true`, the finding was made by
analyzing a single file in isolation. During the audit's Phase 3, Osoji
checks cross-file evidence (imports, calls, symbol references) to determine
whether the finding is a true positive or false positive.

For example, a function flagged as `dead_code` in one file may actually be
imported and called from another file. Phase 3 uses the facts database to
verify this and suppresses false positives.

### Findings staleness

Findings files also have `source_hash` and `impl_hash` fields. They follow
the same staleness rules as shadow docs: if the source file or the Osoji
implementation changes, the findings are considered stale and will be
re-generated on the next `osoji shadow .` run.

---

## Step 11: Using alternate providers and models

Shadow generation uses the configured "medium" model tier. You can override
this per command:

```bash
# Use OpenAI
osoji shadow . --provider openai --model gpt-5.2

# Use Google Gemini
osoji shadow . --provider google --model gemini-2.0-flash

# Use OpenRouter
osoji shadow . --provider openrouter --model openai/gpt-5-mini
```

### TOML configuration for defaults

Instead of passing flags every time, set defaults in TOML config files:

**Global** (`~/.config/osoji/config.toml`):

```toml
default_provider = "openai"

[providers.openai]
small = "gpt-5-mini"
medium = "gpt-5.2"
large = "gpt-5.4"
```

**Per-project** (`.osoji.local.toml`, add to `.gitignore`):

```toml
default_provider = "google"

[providers.google]
medium = "gemini-2.0-flash"
```

Check the effective config:

```bash
osoji config show .
```

### Rate limits

Osoji applies provider-specific rate limits by default. Override with
environment variables:

```bash
export ANTHROPIC_RPM=4000
export ANTHROPIC_INPUT_TPM=2000000
export OPENAI_RPM=500
export OPENAI_INPUT_TPM=500000
```

Use `{PROVIDER}_RPM`, `{PROVIDER}_INPUT_TPM`, and `{PROVIDER}_OUTPUT_TPM`
for fine-grained control.

---

## Step 12: Using shadow docs with AI agents

Shadow documentation is designed to be consumed by AI coding agents as a fast
context layer. Instead of reading entire source files, an agent can read
shadow docs to get structural understanding at a fraction of the token cost.

The recommended reading order for an AI agent:

1. `_root.shadow.md` -- Start here for a project overview.
2. `_directory.shadow.md` -- Drill into specific directories.
3. `<file>.shadow.md` -- Read per-file summaries for specific files.

This is documented in the `CLAUDE.md` file at the project root:

> **For coding agents**: read shadow docs instead of parsing entire files.
> They give you the same structural understanding in a fraction of the tokens.

### Measuring compression

Use `osoji stats` to see how much token savings shadow docs provide:

```bash
osoji stats .
```

```
============================================================
OSOJI TOKEN STATISTICS
============================================================

Files analyzed:      15
Files with shadows:  15

Source tokens:       5,200
Shadow tokens:       2,080

Compression ratio:   40.00%
Token savings:       60.0%

============================================================
```

A compression ratio of 40% means shadow docs are about 40% the size of the
original source. Token savings of 60% means an AI agent saves 60% of context
window by reading shadow docs instead of source files.

---

## Wrap-up

You have learned the complete shadow documentation lifecycle:

1. **Generate**: Run `osoji shadow .` to create shadow docs for your codebase.
2. **Cache**: Only changed files are regenerated on subsequent runs (hash-based
   staleness detection using SHA-256 truncated to 16 hex characters).
3. **Check**: Use `osoji check .` to identify stale docs without regenerating.
4. **Regenerate**: Re-run `osoji shadow .` to update stale docs.
5. **Clean up**: Orphaned sidecar files are automatically removed when source
   files are deleted.

### The `.osoji/` directory at a glance

| Path | Contents |
|------|----------|
| `.osoji/shadow/*.shadow.md` | Per-file shadow documentation |
| `.osoji/shadow/_directory.shadow.md` | Per-directory roll-up summaries |
| `.osoji/shadow/_root.shadow.md` | Project root roll-up |
| `.osoji/facts/*.facts.json` | Imports, exports, calls, string literals |
| `.osoji/symbols/*.symbols.json` | Function/class/constant definitions |
| `.osoji/findings/*.findings.json` | Code debris findings |
| `.osoji/signatures/*.signature.json` | Topic signatures for coverage analysis |
| `.osoji/staleness.json` | Staleness manifest (written by `osoji check`) |

### Next steps

- **Running Your First Documentation Audit** (tutorial) -- Use shadow docs
  as the foundation for documentation auditing.
- **Using Doc Prompts to Fill Documentation Gaps** (tutorial) -- Generate
  writing prompts for missing documentation based on concept-level coverage.
