# scripts\corpus_replay.py
@source-hash: eb2a17a3c27e9486
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:45Z

## Purpose
CLI entrypoint for the corpus-replay evaluation pipeline. Thin argparse shell over `eval_lib.py` — parses arguments, validates flag combinations, delegates all evaluation logic to `eval_lib`, and writes `osoji-verdict/1` NDJSON output. Exit codes: 0=success/gate-passed, 1=gate-failed, 2=argument/setup error.

## Key Symbols

### `DEFAULT_BOOTSTRAP_MANIFEST` (L44)
Fallback bootstrap manifest path (`tests/fixtures/bootstrap/manifest.json`) used when `--source bootstrap/both` is given but `--bootstrap` is not.

### `SPLIT_CHOICES` (L46)
Tuple `("train", "val", "holdout")` — valid values for `--split` argument.

### `_parse_only(raw)` (L49–52)
Converts comma-separated `--only` string into a tuple of stripped keys. Returns empty tuple for falsy input.

### `_parse_variants(specs)` (L55–69)
Resolves `--variant` spec strings via `eval_lib.resolve_variant()`. Enforces no duplicate variant names. Defaults to `["baseline=@default"]` when `specs` is None/empty. Raises `ValueError` on duplicates.

### `_print_gate_report(report)` (L72–81)
Formats and prints a `GateReport` to stdout. Shows pass/fail status, counts, split coverage, missing and extra case keys.

### `build_arg_parser()` (L84–116)
Constructs the `argparse.ArgumentParser`. Key arguments:
- `--corpus` (Path, default: `CORPUS_ROOT`): corpus-case/1 root
- `--bootstrap` (Path, default: None): manifest.json for bootstrap cases
- `--source` (choices: corpus/bootstrap/both, default: corpus): case source
- `--variant` (repeatable, e.g. `name=@default`): evaluation variants
- `--repeats` (int, default: 1): repeat count
- `--repeat-offset` (int, default: 0): repeat numbering offset
- `--run-id` (str, default: None → auto-generated)
- `--split` (choices: train/val/holdout): requires splits.json
- `--only` (str): comma-separated case key filter
- `--exclude-gray` (flag): skip gray-labeled cases
- `--provider` (default: "anthropic")
- `--model` (default: None): model override
- `--out` (default: "-"): NDJSON output path or stdout
- `--gate-check` (flag): evaluate GEPA gate, no LLM calls

### `_load_splits_for(corpus_root)` (L119–121)
Helper: loads splits.json from `corpus_root/splits.json` via `eval_lib.load_splits`.

### `_Utf8BytesWriter` (L124–141)
Adapter class wrapping a binary buffer (`sys.stdout.buffer`) to expose a `.write(str)` interface. Encodes text as UTF-8 bytes and flushes immediately. Prevents Windows `TextIOWrapper` from translating `\n` → `\r\n`, guaranteeing bare-`\n` in output (required by `osoji-verdict/1` spec).

### `main(argv)` (L144–264)
Core orchestration. Flow:
1. Parse args (L145–146)
2. **Validation — incompatible flag combos** (L152–192):
   - `--gate-check` + filters → exit 2
   - `--split` + `--source bootstrap` → exit 2
   - Unknown split name → exit 2
3. Parse `--only` and `--variant` (L170–176)
4. Load splits.json if `--split` given (L178–192)
5. Resolve bootstrap manifest (L194–196)
6. Select cases via `select_cases()` (L198–210); exit 2 if empty
7. **Gate-check branch** (L216–227): load splits, run `check_gepa_gate`, print report, exit 0/1
8. **Evaluation branch** (L229–263):
   - Build `run_id` (L229)
   - Define `_config_factory` closure (L231–237) creating `Config` with provider/model
   - Run `evaluate_corpus` async in temp dir (L240–255)
   - Write NDJSON to stdout (`_Utf8BytesWriter`) or file path (L260–263)
   - Return 0

## Architectural Notes
- All evaluation logic is delegated to `eval_lib`; this file is ~pure CLI plumbing
- `asyncio.run()` bridges sync CLI into async `evaluate_corpus`
- `tempfile.TemporaryDirectory` provides isolated workdir for each run
- `sys.path` is mutated at module level (L26–27) to allow importing `eval_lib` and `osoji` from repo-relative paths without installation
- Consumed both as a direct script and by the proctor corpus-replay harness (osojicode/work#63)
