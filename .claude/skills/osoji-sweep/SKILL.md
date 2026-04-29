---
name: osoji-sweep
description: End-to-end audit — triage every finding, fix problems, file GitHub issues for osoji improvements
arguments: Optional flags like --skip-audit
---

You are running a **complete end-to-end audit** of the current working directory
project. This means: run the audit, triage every finding, fix every true positive
in this repo, and file GitHub issues for osoji pipeline improvements.

## Exhaustive Thoroughness — Non-Negotiable

This is the defining value of AI-assisted auditing. You can review every finding
without fatigue. These rules override any instinct to sample, group-to-skip, or
take shortcuts:

1. **Review EVERY warning and error finding.** Not a sample. Not "representative
   examples." Not grouped summaries. If there are 200 findings, review all 200.
   Use sub-agents to parallelize if needed, but do not skip findings.

2. **Fix documentation substantively.** When a doc finding says content is stale
   or inaccurate, read the actual source code and write correct content. NEVER:
   - Add a "last-modified" date or timestamp
   - Insert a "needs update" or "TODO: update" banner
   - Add a disclaimer ("this may be outdated") instead of correcting
   - Summarize vaguely when specific details are available
   The fix must make the documentation **accurate right now**.

3. **Fix code substantively.** When dead code is confirmed, delete it — don't
   comment it out. When a parameter is dead, remove it and update all call sites.
   When an obligation violation exists, apply the real remediation (extract a
   shared constant, rename to match, etc.) — don't add a TODO comment.

4. **100% of true positives addressed.** If a fix is genuinely ambiguous or risky,
   flag it explicitly in the summary — but the default is to fix it, not skip it.

## Osoji Source Code

The osoji codebase is available for studying false positives and missed detections:

- **GitHub**: `https://github.com/osojicode/osoji`
- **Key entry points**: `src/osoji/audit.py` (orchestration), `src/osoji/cli.py`
  (CLI commands), `src/osoji/tools.py` (LLM tool schemas), system prompts in
  the calling modules (`shadow.py`, `audit.py`, `doc_analysis.py`, etc.)

If osoji is installed locally, read its shadow docs at `.osoji/shadow/` in the
osoji repo to orient yourself before diving into source files.

## Arguments

$ARGUMENTS

- `--skip-audit` — skip Phase 1 and reuse the cached audit result.
- `--push` — upload the observatory bundle to osoji-teams after the audit
  completes but before fixes begin (Phase 1.5). Without this flag the upload
  is skipped entirely.

## Data Hygiene

**Never read pre-existing files from `/tmp` or any temp directory.** Stale files
from previous sessions can persist there and silently feed you wrong data. If you
create intermediate files (e.g. to process a large number of findings), always
write them fresh yourself in the current session — never assume a file in `/tmp`
is current just because it exists. If a command fails, re-run it rather than
falling back to whatever is already on disk.

---

## Phase 0: Setup — Capture Context

Before anything else, capture metadata that will be needed throughout:

```bash
# Commit being audited (for GitHub issue references)
git rev-parse HEAD

# Project name
basename $(git rev-parse --show-toplevel)

# Remote URL (for issue context)
git remote get-url origin 2>/dev/null || echo "no remote"
```

Store the commit hash, project name, and remote URL — you will reference these in
Phase 6 when filing GitHub issues.

---

## Phase 1: Run Full Audit

**Skip this phase if `$ARGUMENTS` contains `--skip-audit`.**

Run the full osoji audit:

```bash
osoji audit --full . 2>&1 | python -c "
import sys
lines = []
for line in sys.stdin:
    lines.append(line)
    if len(lines) <= 50 or 'Phase' in line or 'error' in line.lower():
        sys.stdout.write(line)
print(f'\n--- {len(lines)} total lines of output ---')
"
```

**Important:**
- Use `osoji` directly — it is a console_scripts entry point. Do NOT use
  `python osoji` or `python -m osoji`.
- The audit exits with code 1 when errors are found. This is expected — proceed
  regardless.
- `--full` enables all optional analyses: junk, obligations, and doc-prompts.
  This may take several minutes.

---

## Phase 1.5: Upload Observatory Bundle (opt-in)

**Skip this phase unless `$ARGUMENTS` contains `--push`.**

Upload the audit results **now**, before any files are modified by fixes. This
ensures the bundle reflects the codebase as-audited, not post-fix (where
staleness detection would flag every changed file). This is NOT a git push —
it uploads audit data to the osoji-teams observatory API.

Before running the command, print a clear message so the user knows what is
about to happen:

> Uploading audit results to your configured osoji-teams endpoint at ENDPOINT_URL…

To resolve the endpoint for the message, read it from (in priority order):
`OSOJI_ENDPOINT` env var, `.osoji.toml` `[push].endpoint`, or
`~/.config/osoji/config.toml` `[push].endpoint`.

Then run:

```bash
osoji push 2>&1
```

- If the push succeeds, note it for the Phase 7 summary.
- If it fails (missing endpoint, token, or project config), report the error
  and continue — do NOT prompt the user for credentials or attempt to
  configure push.

---

## Phase 2: Collect Audit Data

Extract the JSON report into workable data:

```bash
osoji report . --format json 2>/dev/null | python -c "
import json, sys
data = json.load(sys.stdin)
print(f'Passed: {data[\"passed\"]}')
print(f'Errors: {data[\"errors\"]}, Warnings: {data[\"warnings\"]}, Infos: {data[\"infos\"]}')
print(f'Total issues: {len(data[\"issues\"])}')
print()
for i in data['issues']:
    if i['severity'] != 'info':
        print(f'{i[\"severity\"]:7s} | {i[\"category\"]:30s} | {i[\"path\"]}:{i.get(\"line_start\",\"?\")}')
        print(f'  {i[\"message\"][:200]}')
"
```

If this fails with "No cached audit result", tell the user to run without
`--skip-audit`.

The JSON output is typically large. Always pipe through Python to extract what
you need rather than trying to capture the raw JSON. When you need full detail
of specific findings (remediation text, metadata), filter by category or path:

```bash
osoji report . --format json 2>/dev/null | python -c "
import json, sys
data = json.load(sys.stdin)
for i in data['issues']:
    if i['category'] == 'TARGET_CATEGORY':
        print(json.dumps(i, indent=2))
"
```

---

## Phase 3: Triage — Classify Every Finding

For **every** warning and error finding (not infos):

### Step 1: Read the target file

Read the file at the path indicated by the finding. If `line_start`/`line_end`
are present, focus on those lines with ~20 lines of surrounding context. If they
are null, read the relevant portion of the file.

### Step 2: Assess the finding

Determine whether this is:

- **True positive**: The finding correctly identifies a real issue. Draft a
  concrete, specific fix:
  - For code: "delete lines 45-62", "rename X to Y", "remove parameter Z and
    update 3 call sites"
  - For docs: write the corrected text based on reading the actual source code

- **False positive**: The finding is wrong — the code or documentation is
  actually fine. Note the category and proceed to root-cause analysis (see below).

- **Downgrade to info**: The specific issue reported is inaccurate BUT the code
  pattern that triggered detection is itself worth noting.

- **Missed finding**: While reading the file for context, you noticed a real
  issue that osoji did NOT report. Note: file path, line range, what the issue
  is, and what osoji category it should fall under (e.g. `dead_symbol`,
  `dead_parameter`, `latent_bug`, `stale_comment`). These feed into
  Phase 6 as missed-detection improvement ideas.

### Step 3: For false positives — trace through osoji pipeline

1. Read the finding's `category` field.
2. In the osoji repo, explore `src/osoji/audit.py` to find which phase produces
   findings with that category.
3. Follow the code into the specific module that generates those findings.
4. Read the system prompts and tool schemas in `src/osoji/tools.py` if the
   finding comes from an LLM-based analysis phase.
5. Determine:
   - **Root cause**: Which pipeline stage produced the false positive and why?
   - **Suggested improvement**: A specific change that would prevent this class
     of false positive.
   - **False negative risk**: Could this fix cause real issues to be missed?
   - **Language agnosticism**: Does the fix work for all programming languages?

### Step 4: For missed findings — trace through osoji pipeline

For each issue you noticed that osoji missed:

1. Determine which osoji category it should fall under.
2. Identify which pipeline stage *should* have caught it (e.g., `shadow.py`
   debris extraction, `deadcode.py`, `doc_analysis.py`, `obligations.py`).
3. Determine why it was missed: prompt gap, missing heuristic, scope limitation,
   candidate filter too aggressive, etc.
4. Draft a suggested detection approach.

### Parallelization for large finding counts

If there are many findings, use sub-agents to parallelize triage across
finding categories. For example, launch one agent for `dead_symbol` findings,
another for `doc_*` findings, another for `obligation_*` findings. Each agent
must still review every finding in its category — parallelization is for speed,
not for skipping.

### Output

After triage, you should have three lists:

1. **True positives** — each with: file path, line range, category, severity,
   and the specific fix to apply
2. **Pipeline improvement ideas (false positives)** — each with: root cause in
   osoji, suggested change, code examples from the audited project, and the
   assessments above
3. **Missed detections** — each with: file path, line range, what osoji should
   have reported, and which category/phase should have caught it

---

## Phase 4: Create Fix Plan

Produce an ordered plan addressing 100% of true positives:

1. Group fixes by file.
2. Within each file, order edits from **bottom to top** (highest line numbers
   first) so earlier edits don't invalidate line numbers of later ones.
3. Note dependencies: if fix A creates or changes something that fix B depends
   on, order accordingly.
4. For doc fixes, include the actual corrected text you will write (not just
   "update the docs").

Present the plan as a numbered list before executing. Example format:

```
## Fix Plan (N true positives)

### src/foo/bar.py (3 fixes)
1. [dead_symbol] Delete lines 85-102 — unused helper `_old_calc()`
2. [dead_parameter] Remove `verbose` param from `run()` (line 45), update call sites in main.py:12, cli.py:88
3. [latent_bug] Fix off-by-one on line 30 — change `< len(items)` to `<= len(items)`

### docs/api.md (2 fixes)
4. [doc_accuracy_error] Line 34 — rewrite: the `--format` flag accepts `text`, `json`, `html` (not `xml`)
5. [stale_content] Lines 10-25 — rewrite installation section to reflect current pyproject.toml deps

### GitHub Issues to File (M pipeline improvements + K missed detections)
6. [FP: dead_symbol] Dynamic dispatch patterns cause false positives
7. [FP: obligation_implicit_contract] Cross-module re-exports misidentified as violations
8. [MISSED: latent_bug] Unchecked dict access on LLM output not detected
```

---

## Phase 5: Execute Fixes

Apply every fix in the plan:

### For each fix:

1. **Read** the file to verify it is still as expected (guard against concurrent
   changes since the audit ran).
2. **Edit** — apply the fix substantively:
   - **Dead code**: delete it entirely
   - **Dead params**: remove the parameter AND update every call site
   - **Stale/inaccurate docs**: rewrite with correct content based on source code
   - **Accuracy errors**: correct the specific claims to match reality
   - **Obligation violations**: extract shared constant, rename to match, etc.
3. **Re-read** the affected area to confirm the fix looks correct.

### After all fixes:

Run the project's test suite if one exists:

```bash
# Detect test runner (language-agnostic)
if [ -f "pyproject.toml" ] || [ -f "setup.py" ] || [ -f "setup.cfg" ]; then
    python -m pytest --tb=short -q 2>&1 | tail -40
elif [ -f "package.json" ]; then
    npm test 2>&1 | tail -40
elif [ -f "Cargo.toml" ]; then
    cargo test 2>&1 | tail -40
elif [ -f "Makefile" ] && grep -q "^test:" Makefile; then
    make test 2>&1 | tail -40
elif [ -f "go.mod" ]; then
    go test ./... 2>&1 | tail -40
fi
```

If tests fail, investigate and fix. The goal is to leave the project in a passing
state.

### Error handling:

- If a file has changed since the audit and the code at the indicated lines does
  not match what the finding described, skip the fix and note it explicitly in the
  summary with the reason.
- If a fix is genuinely ambiguous (multiple valid interpretations), flag it in the
  summary. But the default is to fix, not skip.

---

## Phase 6: File GitHub Issues for Pipeline Improvements

For each pipeline improvement idea from the triage phase — both false positives
AND missed detections — file a GitHub issue on the osoji repo.

### Filing criteria

Only file issues for improvements that are:
- **General purpose** (language agnostic) — changes to prompts, matching logic,
  verification steps that work for any language
- **AST plugin mediated** — language-specific improvements that should go through
  the AST plugin processing layer

Do NOT file issues for one-off quirks of the audited project that would not
generalize to other codebases.

### Deduplication

Before filing each issue, search for existing similar issues:

```bash
gh issue list --repo osojicode/osoji --state open --search "KEYWORDS" --limit 5
```

If a substantially similar issue already exists, add a comment with the new evidence
rather than creating a duplicate:

```bash
gh issue comment NUMBER --repo osojicode/osoji --body "$(cat <<'EOF'
## Additional evidence

Discovered while auditing **PROJECT_NAME** at commit `COMMIT_HASH`.

### Code example

\`\`\`LANGUAGE
CODE_SNIPPET
\`\`\`

**Finding:** CATEGORY — MESSAGE
EOF
)"
```

### Grouping

Multiple false positives or missed detections with the same root cause should be
filed as a single issue with multiple code examples, not separate issues per finding.

### Issue template — false positive

```bash
gh issue create --repo osojicode/osoji \
  --title "Pipeline: BRIEF_DESCRIPTION" \
  --label "enhancement" \
  --body "$(cat <<'ISSUE_EOF'
## Context

Discovered while auditing **PROJECT_NAME** at commit `COMMIT_HASH`.
Remote: REMOTE_URL

## Problem

DESCRIPTION_OF_FALSE_POSITIVE

### Code examples

```LANGUAGE
RELEVANT_CODE_SNIPPET_5_TO_15_LINES
```

**Finding produced by osoji:**
- Category: `CATEGORY`
- Severity: `SEVERITY`
- Message: MESSAGE_TEXT

## Root Cause

- **Pipeline stage**: `MODULE_NAME` (e.g., `deadcode.py`, `doc_analysis.py`)
- **Mechanism**: PROMPT_ISSUE / MATCHING_LOGIC / MISSING_CONTEXT / FACTS_EXTRACTION_ERROR

DETAILED_EXPLANATION

## Suggested Fix

SPECIFIC_CHANGE — prompt refinement, algorithm adjustment, new heuristic, etc.

## Risk Assessment

- **False negative risk**: COULD_THIS_FIX_SUPPRESS_REAL_ISSUES
- **Language agnosticism**: DOES_THIS_WORK_FOR_ALL_LANGUAGES_OR_NEEDS_AST_PLUGIN

## Constraints (from CLAUDE.md)

- Language agnosticism is non-negotiable
- Principles over catalogs in LLM prompts
- Signal conservation: evaluate FP reduction against TP impact
ISSUE_EOF
)"
```

### Issue template — missed detection

```bash
gh issue create --repo osojicode/osoji \
  --title "Pipeline: missed CATEGORY — BRIEF_DESCRIPTION" \
  --label "enhancement" \
  --body "$(cat <<'ISSUE_EOF'
## Context

Discovered while auditing **PROJECT_NAME** at commit `COMMIT_HASH`.
Remote: REMOTE_URL

## Missed Detection

DESCRIPTION_OF_WHAT_OSOJI_SHOULD_HAVE_CAUGHT

### Code example

```LANGUAGE
RELEVANT_CODE_SNIPPET_5_TO_15_LINES
```

**Expected finding:**
- Category: `EXPECTED_CATEGORY`
- Severity: `EXPECTED_SEVERITY`
- What should have been reported: EXPECTED_MESSAGE

## Analysis

- **Pipeline stage that should detect this**: `MODULE_NAME`
- **Why it was missed**: PROMPT_GAP / MISSING_HEURISTIC / SCOPE_LIMITATION / CANDIDATE_FILTER_TOO_AGGRESSIVE

DETAILED_EXPLANATION

## Suggested Detection Approach

SPECIFIC_CHANGE — new heuristic, prompt addition, candidate expansion, etc.

## Risk Assessment

- **False positive risk**: COULD_THIS_DETECTION_PRODUCE_FALSE_POSITIVES
- **Language agnosticism**: DOES_THIS_WORK_FOR_ALL_LANGUAGES_OR_NEEDS_AST_PLUGIN

## Constraints (from CLAUDE.md)

- Language agnosticism is non-negotiable
- Principles over catalogs in LLM prompts
- Signal conservation: evaluate TP gain against FP risk
ISSUE_EOF
)"
```

---

## Phase 7: Summary Report

After all work is complete, produce a final report:

```
## End-to-End Audit Complete

### Audit
- **Project**: NAME at commit `HASH`
- **Findings**: N errors, M warnings, K infos
- **Triage**: X true positives, Y false positives, Z downgraded to info, W missed detections

### Observatory Upload
- UPLOADED to ENDPOINT at commit `HASH` / SKIPPED (--push not specified) / FAILED (reason)

### Fixes Applied (X true positives)
For each fix:
- **file:line** — [category] what was changed

### Test Results
- PASS / FAIL / no test runner detected
- (details if failures)

### GitHub Issues Filed
For each issue:
- #NUMBER: TITLE (new issue / comment on existing)
  - Type: false positive / missed detection

### Missed Detections (W issues osoji should have caught)
For each:
- **file:line** — what was missed, expected category

### Items Requiring Manual Attention
- (any fixes skipped, with reasons)
- (any borderline FPs that may warrant discussion)
```
