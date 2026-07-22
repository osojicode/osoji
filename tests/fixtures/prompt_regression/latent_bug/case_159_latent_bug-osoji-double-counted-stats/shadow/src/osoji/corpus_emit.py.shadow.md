# src\osoji\corpus_emit.py
@source-hash: a3aa42a8e49a871f
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:04Z

## Purpose
Converts a single decided finding from the osoji audit ledger (`.osoji/analysis/decided-findings.json`) into a review-ready `corpus-case/1` stub directory under a `_holding/` path, suitable for human acceptance into the evaluator fixture corpus via `git mv`. Designed to work when installed as a wheel in any repo (not only the osoji checkout).

## Key Public API

### `emit_case` (L384–545)
Core pure-function entry point. Validates all inputs before any filesystem writes, then writes the case directory atomically (with cleanup-on-failure via `shutil.rmtree`).

**Parameters:**
- `repo_root`: Root of the target repository
- `finding_id`: Content-hash ID from the ledger
- `slug`: URL-safe case name (`[a-z0-9_-]+`)
- `dest`: Destination holding directory (e.g., `_holding/`)
- `expected_verdict`: Override for `"confirmed"` | `"dismissed"` (default: taken from ledger)
- `reasoning`: Override triage reasoning (default: `finding["triage_reasoning"]`)
- `gray`: Marks case as gray/borderline in `expected.json`
- `include`: Extra repo-relative paths to snapshot alongside evidence
- `language`: Override language label in `case.json`

**Output directory layout** (`<dest>/<category>/case_<slug>/`):
- `case.json` — schema `corpus-case/1`, origin metadata, detector/category
- `finding.json` — ledger entry with triage fields stripped (verdict, confidence, reasoning, suggested_fix, severity, contract_class, evidence_fingerprint all set to `None`, evidence cleared)
- `expected.json` — schema `corpus-expected/1`, verdict, reasoning, gray flag
- `source/<rel_path>` — copied source files
- `symbols/<rel_path>.symbols.json`, `facts/<rel_path>.facts.json`, `shadow/<rel_path>.shadow.md` — sidecars from `.osoji/` if present

**Validation sequence (all pre-write):**
1. Slug format (`_validate_slug`, L265–269)
2. Ledger load + schema check (`_load_ledger`, L284–299)
3. Finding lookup with near-miss listing (`_find_finding`, L305–328)
4. Resolve evidence paths via `_evidence_paths` (L198–215) — mechanical string walk
5. Resolve `--include` paths
6. File-count cap: `MAX_FILES = 25` (L47)
7. All paths resolved to existing repo-contained files (`_resolve_within_repo`, L139–161)
8. Verdict resolution (`_resolve_expected_verdict`, L331–344)

### `resolve_dest` (L352–376)
Resolves destination directory with precedence: explicit `dest_override` → `$OSOJI_CORPUS_DEST` → `<repo_root>/tests/fixtures/prompt_regression/_holding`. Raises `CorpusEmitError` if none resolves.

### `CorpusEmitError` (L94–95)
User-facing exception for all validation and I/O failures. Caught by `cli.py` to display clean error messages.

## Schema Constants
- `CORPUS_CASE_SCHEMA = "corpus-case/1"` (L33)
- `CORPUS_EXPECTED_SCHEMA = "corpus-expected/1"` (L34)
- `DECIDED_FINDINGS_SCHEMA = "decided-findings/1"` (L39) — must match what `audit.py`/`run_audit_async` writes
- `ENV_CORPUS_DEST = "OSOJI_CORPUS_DEST"` (L42) — env var for dest fallback
- `MAX_FILES = 25` (L47) — snapshot-bloat guard

## Key Internal Helpers
- `_load_ledger` (L284–299): Reads `.osoji/analysis/decided-findings.json`, validates schema tag
- `_find_finding` (L305–328): Linear scan by `id`; on miss, lists up to `_MAX_NEAR_MISS_LINES = 20` `path -> id` pairs
- `_evidence_paths` (L198–215): Walks all string leaves under `finding["evidence"][*]["payload"]`, tests each against `_resolve_within_repo`; no semantic filtering
- `_resolve_within_repo` (L139–161): Resolves path, guards against `../../` escapes, returns `None` for missing or out-of-repo paths
- `_snapshot_failure_reason` (L164–182): Diagnostic-only re-walk to distinguish "missing" vs "escapes repo"
- `_category_of` (L238–262): Splits `"<producer>:<suffix>"` detector string; `doc:` prefix → `doc_<suffix>` spelling; suffix-less → producer name
- `_producer_of` (L231–235): Extracts producer from detector string
- `_language_for` (L218–228): Extension → language label via `_EXTENSION_LANGUAGES` (L62–91)
- `_git` (L120–136): Best-effort `subprocess.run` for git commands; returns `None` on any failure
- `_to_posix` (L103–106): Normalizes Windows paths to POSIX
- `_posix_join` (L109–117): Joins POSIX-relative paths onto a `Path` base without platform-native parsing
- `_walk_strings` (L185–195): Recursive generator over nested dict/list to yield all string leaves
- `_write_json` (L272–276): Creates parent dirs and writes pretty-printed JSON with `\n` terminator
- `_validate_slug` (L265–269): Raises `CorpusEmitError` if slug doesn't match `^[a-z0-9_-]+$`

## Architectural Notes
- **Atomic writes**: All validation runs before `case_dir` is created; any write-phase exception triggers `shutil.rmtree(case_dir, ignore_errors=True)` (L544) so no half-written case is left
- **Sidecar discovery** uses `_SIDECARS` (L54–58): tuples of `(subdir, suffix)` mirroring `config.py`'s path conventions; sidecar copy is best-effort (`is_file()` check at L499)
- **Detector taxonomy**: `_category_of` maps detector strings to corpus directory names; `doc:` findings get special `doc_` prefix treatment (L260–261)
- **`finding.json` sanitization**: Strips all triage/adjudication fields from the ledger entry before writing (L506–511) so the corpus case contains only the finding structure, not the prior verdict
- **Windows safety**: All path operations use `_to_posix`/`_posix_join` to avoid `Path` platform-native separator issues
- **No import from `audit.py`**: `DECIDED_FINDINGS_SCHEMA` is re-declared here by design to avoid coupling (L35–39 comment)
