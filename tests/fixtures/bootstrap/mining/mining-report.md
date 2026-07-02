# V1-4 trace-mining report (Phase C, osojicode/work#27)

Mined **48** correct traces (`agree: true` rows of `exploration-sdk-summary.json`); excluded 6: `dead_parameter-case_002-error` (gray), `audit-obligation_implicit_contract-002` (verdict miss), `audit-obligation_implicit_contract-007` (gray), `audit-dead_parameter-002` (gray), `audit-latent_bug-002` (gray), `audit-stale_comment-002` (gray)

Audit-entry greps re-executed against the current working tree — minor drift vs the baseline commit is possible and tolerable for classification.

## Per-category observations

### dead_code (11 traces)

- calls/trace: mean 4.5, median 4, max 11; list_dir calls: 1
- % traces with grep shape: import_probe **36%**, symbol **82%**, regex **36%**
- % traces with grep breadth: repo_wide **73%**, scoped **36%**
- % traces with read scope: flagged_region **100%**, same_file_other **36%**, referencing_site **9%**
- first action: grep:symbol ×8, read_file:flagged_region ×3

### dead_parameter (6 traces)

- calls/trace: mean 7.3, median 7.5, max 12; list_dir calls: 5
- % traces with grep shape: symbol **83%**, regex **33%**
- % traces with grep breadth: repo_wide **50%**, scoped **100%**
- % traces with read scope: flagged_region **100%**, same_file_other **67%**, referencing_site **83%**
- first action: read_file:flagged_region ×6

### dead_symbol (4 traces)

- calls/trace: mean 6, median 5.5, max 10; list_dir calls: 0
- % traces with grep shape: import_probe **25%**, symbol **100%**, literal **50%**, regex **25%**
- % traces with grep breadth: repo_wide **100%**, scoped **25%**
- % traces with read scope: flagged_region **100%**, referencing_site **100%**, other_file **25%**
- first action: grep:symbol ×3, read_file:flagged_region ×1

### doc_incorrect_content (2 traces)

- calls/trace: mean 4.5, median 4.5, max 5; list_dir calls: 0
- % traces with grep shape: symbol **100%**, regex **50%**
- % traces with grep breadth: repo_wide **50%**, scoped **50%**
- % traces with read scope: flagged_region **100%**, referencing_site **50%**, other_file **50%**
- first action: read_file:flagged_region ×2

### doc_misleading_claim (1 traces)

- calls/trace: mean 3, median 3, max 3; list_dir calls: 0
- % traces with grep shape: regex **100%**
- % traces with grep breadth: scoped **100%**
- % traces with read scope: flagged_region **100%**, other_file **100%**
- first action: read_file:flagged_region ×1

### doc_obsolete_reference (1 traces)

- calls/trace: mean 5, median 5, max 5; list_dir calls: 0
- % traces with grep shape: symbol **100%**, literal **100%**
- % traces with grep breadth: repo_wide **100%**
- % traces with read scope: flagged_region **100%**, referencing_site **100%**
- first action: grep:symbol ×1

### doc_stale_content (1 traces)

- calls/trace: mean 10, median 10, max 10; list_dir calls: 4
- % traces with grep shape: literal **100%**, regex **100%**
- % traces with grep breadth: scoped **100%**
- % traces with read scope: flagged_region **100%**, shadow_doc **100%**
- first action: list_dir ×1

### latent_bug (7 traces)

- calls/trace: mean 4, median 3, max 8; list_dir calls: 1
- % traces with grep shape: symbol **86%**, regex **43%**
- % traces with grep breadth: repo_wide **14%**, scoped **86%**
- % traces with read scope: flagged_region **100%**, same_file_other **29%**, referencing_site **43%**, other_file **14%**
- first action: grep:symbol ×3, read_file:flagged_region ×3, grep:regex ×1

### misleading_docstring (2 traces)

- calls/trace: mean 2.5, median 2.5, max 4; list_dir calls: 0
- % traces with grep shape: regex **50%**
- % traces with grep breadth: scoped **50%**
- % traces with read scope: flagged_region **100%**, same_file_other **50%**
- first action: read_file:flagged_region ×2

### obligation_implicit_contract (6 traces)

- calls/trace: mean 11, median 11.0, max 13; list_dir calls: 2
- % traces with grep shape: import_probe **17%**, symbol **50%**, regex **100%**
- % traces with grep breadth: repo_wide **17%**, scoped **100%**
- % traces with read scope: flagged_region **100%**, referencing_site **100%**
- first action: grep:regex ×5, grep:symbol ×1

### obligation_violation (2 traces)

- calls/trace: mean 6, median 6.0, max 8; list_dir calls: 0
- % traces with grep shape: symbol **100%**, regex **50%**
- % traces with grep breadth: repo_wide **100%**, scoped **50%**
- % traces with read scope: flagged_region **100%**, referencing_site **100%**
- first action: grep:symbol ×2

### stale_comment (2 traces)

- calls/trace: mean 6.5, median 6.5, max 7; list_dir calls: 0
- % traces with grep shape: symbol **100%**, regex **50%**
- % traces with grep breadth: scoped **100%**
- % traces with read scope: flagged_region **100%**, same_file_other **50%**, referencing_site **50%**
- first action: read_file:flagged_region ×2

### unactuated_config (3 traces)

- calls/trace: mean 9.3, median 9, max 11; list_dir calls: 5
- % traces with grep shape: import_probe **33%**, symbol **100%**, literal **33%**
- % traces with grep breadth: repo_wide **100%**, scoped **100%**
- % traces with read scope: flagged_region **100%**, same_file_other **67%**, other_file **33%**
- first action: read_file:flagged_region ×2, grep:symbol ×1

## Cross-check vs adjudication `evidence_consulted`

No mismatches: every adjudication phrase with a keyword mapping has a matching observed tool call.

## DRAFT evidence-kind proposal (for Checkpoint-1 ratification)

Thresholds: consult-rate ≥ 70% ⇒ required; ≥ 30% ⇒ optional. Rates are lower bounds (max over the kind's mapped observation classes).

**This is a machine draft.** `type_signature` consultation is not mechanically detectable from call inputs (it looks like `other_file` reads); review the latent_bug `other_file` rates and the adjudication notes before finalizing.

| category | required | optional |
|---|---|---|
| dead_code | cross_file_reference, surrounding_code | — |
| dead_parameter | cross_file_reference, surrounding_code | — |
| dead_symbol | cross_file_reference, surrounding_code | — |
| doc_incorrect_content | cross_file_reference, surrounding_code | — |
| doc_misleading_claim | cross_file_reference, surrounding_code | — |
| doc_obsolete_reference | cross_file_reference, surrounding_code | — |
| doc_stale_content | cross_file_reference, surrounding_code, shadow_doc_claim | — |
| latent_bug | cross_file_reference, surrounding_code | — |
| misleading_docstring | surrounding_code | cross_file_reference |
| obligation_implicit_contract | cross_file_reference, surrounding_code | — |
| obligation_violation | cross_file_reference, surrounding_code | — |
| stale_comment | cross_file_reference, surrounding_code | — |
| unactuated_config | cross_file_reference, surrounding_code | — |
