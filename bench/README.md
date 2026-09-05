# Documentation-drift benchmark

Ground truth for measuring how much real documentation drift osoji finds,
mined from the git history of open-source repositories. One directory per
repository; the tooling lives in `scripts/bench/`.

## Idea

A commit that touches only documentation and changes or removes existing
lines is a *docs-fix*: at its parent, those lines were wrong about the code.
Checking out the parent and running a documentation checker over the
touched docs asks the only question that matters: did it flag the lines a
maintainer later corrected? Recall is mechanical and abundant. Precision
still needs adjudication, because the checker also flags lines nobody has
fixed yet, and some of those are real.

## Layout

```
bench/
  README.md              this file
  repos.toml             the repository list: clone URL, pinned window, split
  <repo>/
    commits.jsonl        one line per docs-fix commit (sha, parent, files, counts)
    rows.jsonl           one line per corrected hunk group at the parent, unlabeled
    rows.labeled.jsonl   the same rows with one label per reader
```

Repositories are partial clones outside this tree (`~/projects/bench-repos/`
by convention); the benchmark stores commit shas and quoted diff lines, not
the repositories.

## Row schema

Superset of the PR #643 inventory consumed by `scripts/join_inventory_findings.py`.

| field | meaning |
|---|---|
| `row_id` | `<repo>:<sha10>:<n>` |
| `repo`, `commit`, `parent`, `commit_date`, `subject` | provenance |
| `path`, `renamed_to` | the doc at the parent (and its new name, if the fix renamed it) |
| `old_start`, `old_len`, `new_start`, `new_len` | line ranges, parent side first |
| `hunk_count`, `hunk_seqs`, `old_starts` | adjacent hunks merged into one row |
| `minus_text`, `plus_text` | the lines removed at the parent and added by the fix |
| `context_before`, `context_after` | surrounding parent-side lines |
| `labels` | `{reader: label}` or null |

A label carries `partition` (correction, deletion, addition, restructure,
generated, other), `domain` (checkout, world, runtime, or null; see
`osojicode/wiki decisions/0029`), `kind` (the PR #643 taxonomy plus
`other`), `claim_shape` (path, script, symbol_signature, behaviour,
enumeration, value, other), a one-sentence `claim`, an `evidence_path`,
`reasoning`, `confidence`, and the reader's `model`.

Only rows labeled `correction` or `deletion` with `domain = checkout` count
toward recall. `claim_shape` is what an extractor has to recognise; it is
labeled from the row's own text, never inferred from `kind`.

## Rules

- **Splits are by repository**, never by file: dev repos are tuned on,
  validation repos select between candidates, holdout repos are run only at
  phase gates. `repos.toml` records the split; changing it is a benchmark
  version bump.
- **Labels are ground truth, not tuning material**, so every repo including
  holdout is labeled. Running osoji against holdout repos is what is gated.
- **Every closed set has an `other` outlet** and the `other` rate is reported.
- **Readers are recorded, not merged.** Repeated runs add labels under new
  reader keys; consensus and reader-versus-owner agreement are computed
  from the recorded labels, never overwritten into them.
- **Cost is recorded** from `.osoji/logs/llm-interactions.jsonl`
  (reservation key `bench.label`) alongside any labeling run.

## Workflow

```bash
git clone --filter=blob:none --no-checkout https://github.com/<owner>/<name>.git ~/projects/bench-repos/<name>
python scripts/bench/mine.py  --repo ~/projects/bench-repos/<name> --name <name> --since "24 months ago" --out bench/<name>
python scripts/bench/label.py --rows bench/<name>/rows.jsonl --out bench/<name>/rows.labeled.jsonl --reader sonnet-r1
```

The design and the phase gates this benchmark serves are in
`osojicode/wiki specs/0005`.
