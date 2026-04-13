# Using Doc Prompts to Fill Documentation Gaps

This tutorial teaches you how to use Osoji's doc-prompts feature to analyze
documentation coverage at the concept level and generate targeted writing
prompts for missing documentation.

**Time estimate**: 20-30 minutes.

**Prerequisites**:

- Osoji installed and configured with an LLM API key.
- Shadow documentation generated for your target project (see the
  *Generating Shadow Documentation* tutorial).
- A completed audit to understand your baseline coverage (see the
  *Running Your First Documentation Audit* tutorial).
- Basic familiarity with the Diataxis framework (tutorials, how-to guides,
  reference docs, explanatory docs).

---

## What are doc prompts?

Standard Osoji audits measure documentation coverage at the **file level** --
which source files are referenced by at least one doc. This is useful but
limited. A README might mention a file by name without actually explaining how
to use it.

Doc prompts go deeper. They analyze coverage at the **concept level**:

1. Osoji clusters your source files into 15-25 high-level concepts (e.g.,
   "Rate Limiting", "Authentication Middleware", "Database Models").
2. For each concept, it determines which Diataxis documentation types are
   appropriate (tutorial, how-to, reference, explanatory).
3. It cross-references existing docs to find which concepts have partial or
   missing coverage.
4. For each gap, it generates a **self-contained writing prompt** -- a
   complete specification that you (or an AI writing assistant) can use to
   produce the missing documentation.

The result is not just "you need more docs" but "write a how-to guide for
the Rate Limiting concept, covering these specific topics, aimed at this
audience, following these quality criteria."

---

## Step 1: Run the doc-prompts pipeline

There are two ways to trigger doc prompts:

### Option A: As part of a full audit

```bash
osoji audit . --doc-prompts
```

Or run everything:

```bash
osoji audit . --full
```

The `--full` flag is equivalent to `--junk --obligations --doc-prompts`.

### Option B: Standalone (still requires prior audit)

Doc prompts require a scorecard from a completed audit. If you have already
run an audit, you can run doc prompts as part of a new audit:

```bash
osoji audit . --doc-prompts
```

### What happens during the pipeline

The doc-prompts pipeline runs as Phase 5.5, after the scorecard is built in
Phase 5. It has five stages:

| Stage | Name | Type | Description |
|-------|------|------|-------------|
| 0 | Metadata loading | Pure Python | Loads file-level topic signatures, file roles, fan-in counts, and public symbol counts from `.osoji/signatures/`, `.osoji/symbols/`, and `.osoji/facts/`. |
| 1+2 | Concept inventory | LLM | Clusters file-level topics into 15-25 codebase-level concepts. For each concept, assigns a role and determines which Diataxis types are appropriate. Combined into a single LLM call. |
| 3 | Coverage mapping | Pure Python | Cross-references concepts against existing documentation (from the scorecard's `CoverageEntry` data) to find covered, partially covered, and undocumented concepts. |
| 4a | Priority + clustering | Pure Python | Computes priority scores and clusters related concepts. |
| 4b | Writing prompt generation | LLM | Generates self-contained writing prompts for each documentation gap. |

During a verbose audit, you see timing and counts:

```
Osoji: Building concept inventory and writing prompts...
  [phase 5.5 doc prompts: 8.3s] 18 concepts, 12 prompts
```

### Verification checkpoint

After running with `--doc-prompts`:

1. The console report includes a "Documentation Opportunities" section.
2. The JSON output (if `--format json`) includes a `doc_prompts` key.
3. The scorecard includes concept coverage metrics.

---

## Step 2: Read the concept inventory

The concept inventory is the core output of Stages 1+2. Each concept
represents a coherent, documentable unit -- roughly what you would see as a
chapter heading in a developer guide.

In the console report, the concept inventory appears in the "Documentation
Opportunities" section:

```
## Documentation Opportunities

18 concepts. 6 fully documented, 7 partially, 5 undocumented. 15 gap(s),
12 prompt(s).

- [HIGH] **CLI Interface** -- missing: tutorial
- [HIGH] **Authentication Pipeline** -- missing: how-to, reference
- [HIGH] **Rate Limiting** -- missing: reference, explanatory
- [MEDIUM] **Database Models** -- missing: reference
- [MEDIUM] **Configuration System** -- missing: how-to
- [MEDIUM] **Error Handling** -- missing: how-to, reference
- [LOW] **Test Utilities** -- missing: how-to
- [LOW] **Logging Infrastructure** -- missing: reference
```

In the JSON output, each concept has full detail:

```json
{
  "concepts": [
    {
      "concept_id": "auth-pipeline",
      "concept_name": "Authentication Pipeline",
      "concept_description": "JWT-based authentication with middleware, token validation, and role-based access control.",
      "source_files": [
        "src/auth/middleware.py",
        "src/auth/tokens.py",
        "src/auth/roles.py"
      ],
      "concept_role": "public_api",
      "appropriate_types": ["tutorial", "how-to", "reference"],
      "appropriateness_rationale": "User-facing authentication API consumed by all route handlers. Needs tutorial for onboarding, how-to for common tasks, and reference for API surface.",
      "existing_coverage": [
        {
          "doc_path": "docs/getting-started.md",
          "diataxis_type": "tutorial"
        }
      ],
      "missing_types": ["how-to", "reference"],
      "coverage_status": "partially_documented",
      "priority": "high",
      "priority_score": 8.0,
      "priority_signals": [
        "user-facing (public_api)",
        "high fan-in (7 dependents)",
        "exported public API (12 symbols)"
      ],
      "fan_in": 7,
      "public_count": 12
    }
  ]
}
```

### Concept fields

| Field | Description |
|-------|-------------|
| `concept_id` | Machine-readable identifier. |
| `concept_name` | Human-readable name for the concept. |
| `concept_description` | Brief description of what the concept covers. |
| `source_files` | Source files that belong to this concept. A file can belong to multiple concepts. |
| `concept_role` | Architectural role classification (see below). |
| `appropriate_types` | Diataxis doc types that are genuinely useful for this concept. |
| `appropriateness_rationale` | LLM's reasoning for the type assignments. |
| `existing_coverage` | Docs that already cover this concept, with their Diataxis type. |
| `missing_types` | Diataxis types that are appropriate but have no existing coverage. |
| `coverage_status` | One of `fully_documented`, `partially_documented`, `undocumented`. |
| `priority` | Priority label: `high`, `medium`, or `low`. |
| `priority_score` | Numeric score used to rank concepts. |
| `priority_signals` | Factors contributing to the priority (human-readable). |

### Concept roles

Each concept is classified into one of these roles, which determines the
default set of appropriate documentation types:

| Role | Appropriate types | Description |
|------|-------------------|-------------|
| `public_api` | reference, tutorial, how-to | Exported functions/classes consumed by external users. |
| `cli_command` | reference, how-to | Command-line interface entry points. |
| `configuration` | reference, how-to | Config loading, env vars, settings. |
| `architectural_pattern` | explanatory, reference | Design patterns, cross-cutting concerns. |
| `internal_utility` | reference only | Private helpers, internal plumbing. |
| `integration_point` | how-to, reference | External system connectors. |
| `data_model` | reference (+ explanatory if complex) | Core data structures, schemas. |
| `error_handling` | how-to, reference | Error types, recovery strategies. |
| `testing_infrastructure` | how-to, reference | Test utilities, fixtures, helpers. |

The LLM may override these defaults with justification. For example, a
complex internal utility might warrant an explanatory doc.

---

## Step 3: Understanding coverage mapping

Stage 3 maps existing documentation to concepts using the scorecard's
`CoverageEntry` data. The mapping works as follows:

1. For each concept, collect the source files it spans.
2. For each source file, look up which docs cover it (from the scorecard).
3. The union of covering docs across all source files becomes the concept's
   `existing_coverage`.
4. Compare existing coverage types against `appropriate_types` to find
   `missing_types`.
5. Classify coverage status:
   - **fully_documented**: No missing types.
   - **partially_documented**: Some appropriate types covered, others missing.
   - **undocumented**: No appropriate types covered.

### Coverage summary by Diataxis type

The scorecard (when `--doc-prompts` is enabled) includes concept-level coverage
aggregated by Diataxis type:

```
Concept coverage    6/18 fully, 7 partial, 5 undocumented
```

In the JSON output, this appears as `concept_coverage_by_type`:

```json
{
  "concept_coverage_by_type": {
    "tutorial": {
      "needed": 5,
      "covered": 3
    },
    "how-to": {
      "needed": 12,
      "covered": 6
    },
    "reference": {
      "needed": 16,
      "covered": 10
    },
    "explanatory": {
      "needed": 4,
      "covered": 3
    }
  }
}
```

This tells you that 12 concepts should have how-to guides but only 6 do,
16 should have reference docs but only 10 do, and so on.

---

## Step 4: Understanding priority scoring

Not all documentation gaps are equally important. Osoji computes a priority
score for each concept based on multiple signals:

### Scoring factors

| Factor | Score | Condition |
|--------|-------|-----------|
| User-facing role (`public_api`, `cli_command`) | +3 | Concept serves external users. |
| Operational role (`configuration`, `integration_point`) | +2 | Concept handles config or external systems. |
| Structural role (`architectural_pattern`, `data_model`) | +1 | Concept defines structure or patterns. |
| High fan-in (5+ dependents) | +3 | Many other files depend on this concept. |
| Moderate fan-in (2-4 dependents) | +1 | Some files depend on this concept. |
| Public API surface (any exported symbols) | +2 | Concept has importable symbols. |
| Completely undocumented | +2 | No existing coverage at all. |
| Testing infrastructure | -3 | Testing utilities are low priority for docs. |

### Priority labels

| Label | Score threshold |
|-------|-----------------|
| `high` | Score >= 6 |
| `medium` | Score >= 3 |
| `low` | Score < 3 |

A concept with `public_api` role (+3), high fan-in (+3), and public exports
(+2) gets a score of 8 -- high priority. A concept with `internal_utility`
role (+0), no fan-in (+0), and no public exports (+0) gets a score of 0 --
low priority.

### Priority signals

Each concept includes `priority_signals` -- human-readable explanations of
what contributed to its score:

```json
"priority_signals": [
  "user-facing (public_api)",
  "high fan-in (7 dependents)",
  "exported public API (12 symbols)"
]
```

These signals help you understand *why* a concept is prioritized, not just
*that* it is.

---

## Step 5: Reading generated writing prompts

The most actionable output of the doc-prompts pipeline is the set of writing
prompts. Each prompt is a self-contained specification for one missing
documentation file.

### Prompt structure

In the JSON output, each prompt looks like:

```json
{
  "prompt_id": "auth-pipeline-howto",
  "target_concepts": ["auth-pipeline"],
  "diataxis_type": "how-to",
  "priority": "high",
  "prompt_text": "Write a how-to guide covering common authentication tasks...",
  "shadow_doc_excerpts": [
    {
      "source_file": "src/auth/middleware.py",
      "excerpt": "## Purpose\n\nJWT authentication middleware that validates..."
    }
  ],
  "related_docs": ["docs/getting-started.md"],
  "scope_constraints": "Cover token generation, validation, and refresh. Do not cover role-based access control (separate concept). Reference the getting-started tutorial but do not repeat its content.",
  "output_guidance": {
    "filename": "configuring-authentication.md",
    "directory": "docs/how-to"
  }
}
```

### Prompt fields

| Field | Purpose |
|-------|---------|
| `prompt_id` | Unique identifier for the prompt. |
| `target_concepts` | Which concepts this prompt covers. May span multiple concepts when they are clustered. |
| `diataxis_type` | The Diataxis documentation type to write. |
| `priority` | Inherited from the highest-priority target concept. |
| `prompt_text` | The full writing prompt -- task description, audience, scope, quality criteria. |
| `shadow_doc_excerpts` | Relevant shadow doc excerpts to provide context without re-reading source files. |
| `related_docs` | Existing docs that the writer should reference for consistency. |
| `scope_constraints` | What is in scope and out of scope for this doc. |
| `output_guidance` | Suggested filename and directory for the output. |

### What the prompt text contains

Each `prompt_text` is structured as a complete writing specification:

```
Write a how-to guide titled "Configuring Authentication" that helps
developers set up JWT-based authentication in their application.

## TASK
Write task-oriented documentation covering the common authentication
workflows: generating tokens, validating requests, and refreshing
expired tokens.

## AUDIENCE
Backend developers integrating the authentication module into their
API routes. They understand HTTP and middleware concepts but are new
to this project's auth implementation.

## SCOPE
IN SCOPE: Token generation, request validation middleware setup,
token refresh flow, error handling for invalid tokens.
OUT OF SCOPE: Role-based access control (covered separately),
database schema for user storage, frontend auth flows.

## QUALITY CRITERIA
- Each task should be completable in under 5 minutes.
- Include copy-pasteable code examples.
- Show expected output/behavior for each step.
- Reference the getting-started tutorial for initial setup context.
```

### Concept clustering

When multiple concepts share overlapping source files and the same missing
documentation types, the pipeline clusters them and generates a **single
combined prompt** rather than separate prompts. This avoids redundant docs
that cover the same code from slightly different angles.

Clustering criteria:
- More than 50% source file overlap between concepts.
- At least one shared missing Diataxis type.

Clustered prompts have a `cluster_id` field and list multiple
`target_concepts`.

---

## Step 6: Acting on a prompt

Pick one high-priority prompt and use it to write documentation. There are
two approaches:

### Option A: Write the doc yourself

Use the prompt as a specification. The prompt tells you:

- **What to write** (task description).
- **Who will read it** (audience).
- **What to cover and what to skip** (scope constraints).
- **What "done" looks like** (quality criteria).
- **Where to put it** (output guidance).

The shadow doc excerpts give you a compressed view of the source code's
architecture without reading every file.

For example, if the prompt says to write a how-to guide at
`docs/how-to/configuring-authentication.md`:

```bash
mkdir -p docs/how-to
# Write the doc following the prompt specification
```

### Option B: Feed the prompt to an AI writing assistant

The prompt is designed to be self-contained. You can paste it directly into
an AI assistant (Claude, ChatGPT, etc.) as a writing instruction:

```bash
# Extract the prompt text from JSON output
osoji audit . --doc-prompts --format json | \
  python -c "
import json, sys
data = json.load(sys.stdin)
for p in data.get('doc_prompts', {}).get('writing_prompts', []):
    if p['priority'] == 'high':
        print(p['prompt_text'])
        break
"
```

Copy the output and paste it into your AI assistant, along with the
shadow doc excerpts for context.

### Where to place the resulting doc

The `output_guidance` field suggests a filename and directory:

```json
"output_guidance": {
  "filename": "configuring-authentication.md",
  "directory": "docs/how-to"
}
```

Follow your project's existing documentation structure. If the suggested
directory does not exist, create it:

```bash
mkdir -p docs/how-to
```

---

## Step 7: Re-run to verify improvement

After writing one or more docs, re-run the audit with `--doc-prompts` to see
the gaps close:

```bash
osoji audit . --doc-prompts
```

Compare the new "Documentation Opportunities" section with the previous run:

**Before**:

```
18 concepts. 6 fully documented, 7 partially, 5 undocumented. 15 gap(s),
12 prompt(s).

- [HIGH] **Authentication Pipeline** -- missing: how-to, reference
```

**After** (you wrote the how-to guide):

```
18 concepts. 6 fully documented, 8 partially, 4 undocumented. 13 gap(s),
10 prompt(s).

- [HIGH] **Authentication Pipeline** -- missing: reference
```

The Authentication Pipeline concept moved from "missing: how-to, reference"
to "missing: reference" -- one gap closed. The total gap count dropped from
15 to 13.

### Verification checkpoint

1. The total gap count has decreased.
2. The concept you documented has fewer missing types.
3. The newly written doc appears in the concept's `existing_coverage`.

---

## Step 8: The Diataxis framework in practice

When reading doc-prompt output, understanding the four Diataxis types helps
you decide what kind of documentation each concept needs:

### Tutorial

A **tutorial** is a learning-oriented walkthrough. It takes the reader by the
hand through a series of steps to complete a small project or exercise. The
reader learns by doing.

**When appropriate**: For concepts that newcomers need to understand from
scratch. Typically assigned to `public_api` and `cli_command` concepts.

**Structure**: Prerequisites, numbered steps, verification checkpoints,
wrap-up.

### How-to guide

A **how-to guide** is task-oriented. It answers "How do I accomplish X?"
It assumes the reader already understands the concept and wants practical
steps.

**When appropriate**: For concepts with common tasks that developers perform
repeatedly. Assigned to most roles except `internal_utility` and
`architectural_pattern`.

**Structure**: Goal statement, steps, gotchas, related tasks.

### Reference

**Reference** documentation is information-oriented. It precisely describes
the API surface: function signatures, parameter types, return values, error
conditions, configuration options.

**When appropriate**: For almost every concept. The most universally useful
doc type.

**Structure**: Organized by API surface, complete, scannable, accurate.

### Explanatory

**Explanatory** documentation discusses *why* things work the way they do.
It connects concepts, explains trade-offs, and provides mental models.

**When appropriate**: For architectural patterns, complex data models, and
design decisions that need justification.

**Structure**: Discussion format, connects to broader context, explains
alternatives considered.

---

## Step 9: Understanding the pipeline's data sources

The doc-prompts pipeline draws on several data sources generated during
shadow documentation and previous audit phases. Understanding these helps
you interpret the output and troubleshoot unexpected results.

### Topic signatures (`.osoji/signatures/`)

Each source file gets a `.signature.json` during shadow generation. This
contains:

```json
{
  "path": "src/auth/middleware.py",
  "purpose": "JWT-based request authentication middleware",
  "topics": [
    "JWT validation",
    "request authentication",
    "middleware pipeline",
    "token expiry",
    "role extraction"
  ]
}
```

These topic signatures are the raw input that the LLM clusters into concepts
in Stage 1+2. If a topic signature is missing or vague, the concept inventory
may not accurately represent that file's role.

**Fix**: Re-run `osoji shadow .` to regenerate signatures if they seem stale
or inaccurate.

### File roles (`.osoji/symbols/`)

The `file_role` field from shadow generation classifies each file's
architectural role (e.g., `service`, `schema`, `types`, `controller`,
`utility`). This is distinct from the concept role -- file roles describe
individual files, while concept roles describe clusters of files.

### Fan-in counts (`.osoji/facts/`)

Fan-in is computed from the facts database: how many other files import a
given file. High fan-in means the file is widely depended upon and therefore
more important to document.

### Public symbol counts (`.osoji/symbols/`)

The number of `public` (non-underscore-prefixed, exported) symbols in a file
contributes to the priority score. Files with many public symbols represent
larger API surfaces that benefit more from documentation.

### Scorecard coverage entries

Stage 3 uses the `CoverageEntry` data from the scorecard (built in Phase 5
of the audit). Each `CoverageEntry` maps a source file to its covering docs:

```python
@dataclass
class CoverageEntry:
    source_path: str
    topic_signature: dict | None
    covering_docs: list[dict]  # [{"path": str, "classification": str}]
```

The coverage mapping in Stage 3 aggregates these per-file entries across all
files in a concept to determine concept-level coverage.

---

## Step 10: Interpreting the JSON output in detail

The full JSON output from `--doc-prompts` includes both the concept inventory
and the writing prompts. Here is a complete example for a small project:

```bash
osoji audit . --doc-prompts --format json > audit.json
```

Extract just the doc-prompts section:

```bash
python -c "
import json
with open('audit.json') as f:
    data = json.load(f)
dp = data.get('doc_prompts', {})
print(json.dumps(dp, indent=2))
"
```

The structure:

```json
{
  "concepts": [ ... ],
  "writing_prompts": [ ... ],
  "total_concepts": 18,
  "fully_documented": 6,
  "partially_documented": 7,
  "undocumented": 5,
  "coverage_by_type": {
    "tutorial": {"needed": 5, "covered": 3},
    "how-to": {"needed": 12, "covered": 6},
    "reference": {"needed": 16, "covered": 10},
    "explanatory": {"needed": 4, "covered": 3}
  },
  "total_gaps": 15,
  "total_prompts": 12
}
```

Note that `total_prompts` (12) is less than `total_gaps` (15). This is
because some concepts are clustered, producing combined prompts that cover
multiple gaps.

### Extracting high-priority prompts

To extract just the high-priority writing prompts:

```bash
python -c "
import json
with open('audit.json') as f:
    data = json.load(f)
for p in data.get('doc_prompts', {}).get('writing_prompts', []):
    if p.get('priority') == 'high':
        print(f\"--- {p['prompt_id']} ({p['diataxis_type']}) ---\")
        print(p['prompt_text'][:500])
        print()
"
```

### Extracting undocumented concepts

To see which concepts have zero documentation:

```bash
python -c "
import json
with open('audit.json') as f:
    data = json.load(f)
for c in data.get('doc_prompts', {}).get('concepts', []):
    if c.get('coverage_status') == 'undocumented':
        types = ', '.join(c.get('appropriate_types', []))
        print(f\"{c['concept_name']}: needs {types}\")
"
```

---

## Step 11: Iterative documentation improvement

You do not need to fill all gaps at once. The doc-prompts workflow is designed
for iterative improvement:

1. **Run the audit** with `--doc-prompts`.
2. **Pick the highest-priority gap** from the output.
3. **Write one doc** using the generated prompt as specification.
4. **Re-audit** to verify the gap closed.
5. **Repeat** with the next highest-priority gap.

Over time, your concept coverage improves and the doc-prompts output shrinks.
When all concepts are fully documented, the output shows:

```
18 concepts. 18 fully documented, 0 partially, 0 undocumented. 0 gap(s),
0 prompt(s).
```

### Prioritization strategy

Focus on high-priority concepts first because they:

- Serve external users (`public_api`, `cli_command`).
- Have many dependents (high fan-in).
- Export public API surface.
- Are completely undocumented.

Low-priority concepts (testing infrastructure, internal utilities with no
dependents) can be documented later or left with code-level documentation
only.

### Tracking progress over time

Run `--doc-prompts` periodically and compare the summary line:

```
Run 1:  18 concepts. 6 fully, 7 partially, 5 undocumented. 15 gaps.
Run 2:  18 concepts. 8 fully, 7 partially, 3 undocumented. 11 gaps.
Run 3:  18 concepts. 12 fully, 5 partially, 1 undocumented. 6 gaps.
Run 4:  18 concepts. 17 fully, 1 partially, 0 undocumented. 1 gap.
```

Each run reflects the docs you have written since the previous run.

---

## Common questions

### Why are some concepts low priority even though they seem important?

Priority scoring is heuristic-based. A concept may seem important to you but
score low because it has:

- Few dependents (low fan-in).
- No exported public symbols.
- An `internal_utility` or `testing_infrastructure` role.

The priority signals field explains the scoring. If you disagree with the
LLM's role classification, re-running the audit may produce different results,
or you can use the prompt text as-is regardless of priority.

### Why do I get fewer prompts than gaps?

Concept clustering combines prompts for concepts that share overlapping source
files and missing types. A cluster of 3 concepts each missing a `reference`
doc produces 1 combined prompt instead of 3 separate prompts.

### Can I run doc-prompts without a full audit?

No. Doc prompts require the scorecard from Phase 5, which requires doc
analysis from Phase 2. You must run at least `osoji audit . --doc-prompts`.
However, if you have already run an audit, the cached shadow docs and findings
make subsequent runs faster.

### How does the concept count relate to file count?

A project with 30 source files might produce 15-25 concepts. The LLM clusters
related files: three authentication-related files might form one "Authentication
Pipeline" concept. A single file might span two concepts if it serves multiple
concerns.

---

## Wrap-up

You have learned the complete doc-prompts workflow:

1. **Audit** -- Run `osoji audit . --doc-prompts` to analyze documentation
   coverage at the concept level.
2. **Identify gaps** -- Read the concept inventory and coverage mapping to
   understand which concepts need which types of documentation.
3. **Prioritize** -- Focus on high-priority concepts based on role, fan-in,
   and public API surface.
4. **Generate prompts** -- Use the self-contained writing prompts as
   specifications for writing or for feeding to AI assistants.
5. **Write docs** -- Follow the prompt's task, audience, scope, and quality
   criteria.
6. **Verify** -- Re-run with `--doc-prompts` to confirm the gap has closed.

The doc-prompts feature bridges the gap between "your coverage score is 67%"
and "here is exactly what to write to improve it." By generating targeted,
self-contained writing prompts, it turns documentation debt into a manageable
backlog of well-defined tasks.

### Next steps

- **Protecting Your Repository with Safety Checks** (tutorial) -- Set up
  pre-commit safety scanning for personal paths and secrets.
- **Getting Started with the CLI** (tutorial) -- Review if you need a
  refresher on other Osoji commands.
