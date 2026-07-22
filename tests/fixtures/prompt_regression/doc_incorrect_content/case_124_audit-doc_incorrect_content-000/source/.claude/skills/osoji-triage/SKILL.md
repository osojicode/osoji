---
name: osoji-triage
description: Triage findings and produce a structured report (read-only, no fixes)
arguments: Optional category or path filter
---

You are reviewing the audit findings from an osoji audit of the CURRENT working
directory project. Your goal is to classify each finding as a true positive, false
positive, or downgrade to info, then propose improvements for both this repo and
osoji itself.

## Osoji Source Code

The osoji codebase is available for studying false positives and missed detections:

- **GitHub**: `https://github.com/osojicode/osoji`
- **Key entry points**: `src/osoji/audit.py` (orchestration), `src/osoji/cli.py`
  (CLI commands), `src/osoji/tools.py` (LLM tool schemas)

If osoji is installed locally, read its shadow docs at `.osoji/shadow/` in the
osoji repo to orient yourself before diving into source files.

## Arguments

$ARGUMENTS

If arguments are provided, treat them as a filter: only review findings matching those
categories or file paths. If no arguments, review all findings.

## Data Hygiene

**Never read pre-existing files from `/tmp` or any temp directory.** Stale files
from previous sessions can persist there and silently feed you wrong data. If you
create intermediate files (e.g. to process a large number of findings), always
write them fresh yourself in the current session — never assume a file in `/tmp`
is current just because it exists. If a command fails, re-run it rather than
falling back to whatever is already on disk.

## Phase A: Collect Audit Data

Run `osoji report . --format json` to get the audit results. **Important:**
- Use `osoji` directly — it is a console_scripts entry point. Do NOT use
  `python osoji` or `python -m osoji` (these will fail).
- If this fails with "No cached audit result", tell the user to run
  `osoji audit .` first (with `--full` for complete analysis).

The JSON output is typically large (hundreds of findings). To avoid output
truncation, pipe through a Python script to extract what you need rather than
trying to capture the raw JSON. For example:
```bash
osoji report . --format json 2>/dev/null | python -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps({'errors': data['errors'], 'warnings': data['warnings'],
                  'infos': data['infos']}, indent=2))
for i in data['issues']:
    if i['severity'] != 'info':
        print(f'{i[\"severity\"]:7s} | {i[\"category\"]:30s} | {i[\"path\"]}:{i.get(\"line_start\",\"?\")}')
        print(f'  {i[\"message\"][:200]}')
"
```

When you need the full detail of specific findings (e.g. remediation text), filter
by category or path in the Python script rather than dumping everything.

## Phase B: Triage Each Finding

For each finding in the issues list:

1. **Read the target file.** Examine the file at the path indicated by the finding.
   If `line_start`/`line_end` are present, focus on those lines with ~20 lines of
   surrounding context. If they are null, read the relevant portion of the file.

2. **Assess the finding.** Determine whether this is:

   - **True positive**: The finding correctly identifies a real issue in this repo.
     Draft a concrete, specific fix (e.g., "delete lines 45-62", "rename X to Y",
     "update the documented flag from --old to --new").

   - **False positive**: The finding is wrong — the code or documentation is
     actually fine and well structured. Note the finding category and proceed to
     Phase C to analyze the osoji pipeline.

   - **Downgrade to info**: The specific issue osoji reported is not accurate BUT
     the code pattern that triggered the detection is itself worth noting or the
     finding is accurate but the issue is not worth addressing (standard practice,
     not misleading). For example, a function flagged as dead code because it is
     only reachable through `getattr()` magic — the function is not dead, but the
     indirection is a legitimate concern for maintainability. The right response is
     not to "fix" the reported issue but to acknowledge the pattern is worth
     reconsidering.

   - **Missed finding**: While reading the file for context, you noticed a real
     issue that osoji did NOT report. Note: file path, line range, what the issue
     is, and what osoji category it should fall under. These are reported in
     Phase D Section 5.

3. **Always read actual source code** before judging. Never rely solely on the
   finding message or the shadow docs.

If there are more than 30 findings, group similar ones and analyze representative
examples rather than every single finding. State which findings you grouped.

## Phase C: Analyze Osoji Pipeline for False Positives and Missed Detections

### For each false positive

Study the osoji source code to understand HOW the false positive was generated
and WHAT could be changed to prevent it.

**How to trace a finding back through the pipeline:**

1. Start by reading the finding's `category` field.
2. In the osoji repo, explore `src/osoji/audit.py` to find which phase produces
   findings with that category.
3. Follow the code into the specific module that generates those findings.
4. Read the system prompts and tool schemas in `src/osoji/tools.py` if the finding
   comes from an LLM-based analysis phase.
5. Identify what went wrong: Was it the prompt? The matching logic? Missing context?
   A limitation of the facts extraction?

**For each false positive, determine:**

- **Root cause**: Which pipeline stage produced the false positive and why?
- **Suggested improvement**: A specific change (prompt fix, algorithm fix, or new
  pipeline stage) that would prevent this class of false positive.
- **False negative risk**: Could this fix cause real issues to be missed?
- **Language agnosticism**: Does the fix work for all programming languages, not
  just the one in this repo? Osoji must remain language-agnostic.

### For each missed detection

1. Determine which osoji category it should fall under.
2. Identify which pipeline stage *should* have caught it (e.g., `shadow.py`
   debris extraction, `deadcode.py`, `deadparam.py`, `doc_analysis.py`,
   `obligations.py`, `plumbing.py`, `junk_cicd.py`, `junk_deps.py`,
   `junk_orphan.py`).
3. Determine why it was missed: prompt gap, missing heuristic, scope limitation,
   candidate filter too aggressive, etc.
4. Draft a suggested detection approach.
5. Assess false positive risk: could adding this detection produce false positives?

**Important context**: Osoji's structured facts (`.osoji/facts/`) come from either
deterministic AST plugin extraction or LLM extraction — the `extraction_method` field
on each fact entry indicates which (`"ast"` for deterministic, `"llm"` for
LLM-extracted). AST-extracted facts are reliable; LLM-extracted facts may contain
errors. When a finding seems wrong, consider whether the underlying facts extraction
was the real culprit rather than the analysis phase that consumed those facts.

## Phase D: Produce Structured Output

Organize your output into these sections:

### 1. Summary

- Total findings: N errors, M warnings, K infos
- Triage: X true positives, Y false positives, Z downgraded to info, W missed detections
- Key scorecard metrics (coverage, accuracy, junk fraction) if available
- One-sentence assessment of audit quality

### 2. True Positives — Issues to Fix in This Repo

For each true positive:
- **File and location** (with line numbers if available)
- **Category** and **severity**
- **The issue** (one sentence)
- **Proposed fix** (specific, actionable)

Group by file when multiple findings affect the same file.

### 3. False Positives — Osoji Pipeline Improvement Opportunities

For each false positive or group of related false positives:
- **Category** and which finding(s)
- **Why it is a false positive** (what the code actually does)
- **Root cause in osoji** (which pipeline stage, what went wrong)
- **Suggested improvement** (be specific — prompt change, algorithm change, etc.)
- **Risk assessment** (could this fix increase false negatives?)
- **Language-agnosticism check** (does the fix work for all languages?)

### 4. Downgraded to Info — Patterns Worth Noting

For each downgraded finding:
- **The finding** and why the specific issue reported is wrong
- **The underlying pattern** that triggered detection and why it is worth noting
- **Suggestion** (optional refactoring that would improve the code independently of
  osoji's analysis)

### 5. Missed Detections — Issues Osoji Should Have Caught

For each issue you noticed while reading files that osoji did not report:

- **File:line** — what the issue is
- **Expected category**: which osoji category should have caught this
  (e.g. `dead_code`, `latent_bug`, `stale_comment`, `obligation_violation`)
- **Expected severity**: `error` or `warning`
- **Pipeline stage**: which osoji module should detect this
  (e.g., `shadow.py` debris, `deadcode.py`, `doc_analysis.py`)
- **Why it was missed**: prompt gap, missing heuristic, scope limitation,
  candidate filter too aggressive, etc.
- **Suggested detection approach**: how osoji could detect this class of issue
- **False positive risk**: could adding this detection produce FPs in other projects?
- **Language agnosticism**: does this work for all languages or need AST plugin support?

### 6. Improvement Ideas

**For this repo:**
- Improvements beyond fixing individual findings (patterns, architecture, docs)

**For osoji** (reference https://github.com/osojicode/osoji):
- Pipeline improvements, prompt refinements, new analysis stages
- Prioritized by impact — how many false positives or missed detections would each fix address?
- All suggestions must keep osoji language-agnostic
