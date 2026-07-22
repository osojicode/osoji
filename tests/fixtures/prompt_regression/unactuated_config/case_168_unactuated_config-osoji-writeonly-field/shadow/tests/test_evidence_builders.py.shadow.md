# tests\test_evidence_builders.py
@source-hash: 23495ba65730395c
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:58:09Z

## Purpose
Test suite for the mechanized evidence builders (V1-4, osojicode/work#27). Covers five builder kinds: `cross_file_reference`, `surrounding_code`, `declared_intent`, `shadow_doc_claim`, and `type_signature`. Tests span schema registration, scanner-metadata steering, scan corpus behavior, robustness, and several specific ablation/regression cases from exploration traces.

## Key Components

### `FakeFacts` (L33–48)
Stub for `FactsDB` interface. Implements:
- `cross_file_references(symbol, source_path)` → list from `_refs` dict (L41–42)
- `exported_names(file_path)` → set from `_exports`, normalizing backslashes (L44–45)
- `all_files()` → list from `_file_list` (L47–48)

Constructor accepts `refs_by_symbol`, `exports_by_file`, `files`. `_file_list` defaults to keys of `_exports` when `files` is `None` (L39).

### `make_finding(**over)` (L51–64)
Factory for `Finding` objects with sane defaults. Default: `detector="debris:dead_code"`, `gap_type="reachability"`, `path="src/x.py"`, `symbol="old_helper"`, lines 10–12. Keyword overrides applied via `base.update(over)`.

### `write(root, rel, text)` (L67–71)
Helper to create files in `temp_dir` with parent directory creation.

### `_with_scanner_meta(finding, **payload)` (L432–443)
Creates a new `Finding` from an existing one, adding an `Evidence(kind="scanner_metadata", payload=payload)` to its `evidence` field. Used to simulate scanner-supplied steering hints. Reconstructs fields via a hardcoded tuple at L438–441.

### `config` fixture (L28–30)
Returns `Config(root_path=temp_dir, respect_gitignore=False)`.

## Test Groups

### Schema/Registration (L74–91)
- `test_new_evidence_kinds_are_registered`: asserts `surrounding_code`, `declared_intent` in `EVIDENCE_KINDS`.
- `test_every_produced_kind_has_a_builder`: asserts all five builder kinds are in `BUILDERS` with matching `.kind` attributes.

### `cross_file_reference` Builder (L94–283)
Extensive tests covering:
- FactsDB integration (L97–107): `refs[0]["source"] == "facts"`.
- Text scan fallback when facts empty (L110–118): finds hits in `y.py`.
- Third-file sweep (L121–129): scan finds `src/z.py` beyond the flagged pair.
- Same-file usage outside flagged region (L132–146): `same_file=True`, `line > 2`.
- Symbolless findings use quoted literals as needles (L149–169): `"ast"` is a needle, not prose words.
- Zero-hit scan is evidence-of-absence (L172–187): empty `references`, non-zero `files_scanned`.
- Empty scope yields no evidence (L190–195): `evidence == []`.
- Export surface reporting (L198–208): `export_surface.exported_from_flagged_file`.
- Word-boundary matching for literal needles (L211–223): `'ast'` must not match `'fastest'`.
- Claim-named files scanned first (L226–241): priority prevents starving specific files.
- Per-needle total reporting (L244–255): `scan_scope.needle_totals["needle_word"] == 30`.
- Context length cap (L258–268): `len(ref["context"]) < 2_000`.
- Per-file hit cap for diversity (L271–283): noisy file capped at ≤3 hits.

### `surrounding_code` Builder (L286–321)
- Extracts flagged region with numbered lines (L289–299).
- Symbol anchor wins over drifted `line_start` (L302–316): `payload["anchor"] == "symbol"`.
- Missing file returns `[]` (L319–321).

### `declared_intent` Builder (L324–358)
- Captures `preceding_lines` and `enclosing_head` blocks (L327–353).
- Missing file returns `[]` (L356–358).

### `shadow_doc_claim` Builder (L361–387)
- Degrades gracefully to `[]` without shadow files (L364–366).
- Reads `.osoji/shadow/src/x.py.shadow.md` (L369–375): `scope == "file"`.
- Adds directory shadow for `gap_type="description"` (L378–387): scopes == `{"file", "directory"}`.

### `type_signature` Builder (L390–415)
- Matches legacy helpers by extracting class name from `contract_claim` backtick text (L393–415).

### Robustness (L419–426)
- All builders return `list` (never raise) on missing file (L421–426).

### Scanner Metadata Steering / V1-5a (L429–663)
- `scan_needles` overrides symbol for text sweep and facts lookups (L446–476).
- `priority_paths` survive hit cap (L479–494).
- `in_string_literal` flag for hits inside quoted strings (L497–506).
- `_match_in_quotes` unit test (L509–517): positional check for quote context.
- Backticked dotted names yield qualified + bare needles (L520–538).
- Backtick call-form extraction `_backticked_names` (L542–556): `name()` pattern fixed (work#58).
- Degenerate bare segment suppression (L559–567): `__init__.py` keeps qualified, drops `py`.
- End-to-end call-form fixture (L570–594): `_discover_entry_point_plugins` found in `__init__.py`.
- Proximity-ordered sweep (L597–612): sibling package file ranks first.
- Scan corpus uses walker, skips `.osoji/` artifacts (L615–622).
- Truncated corpus: flagged file still swept (L625–643), zero-sweep not a mechanical proof (L646–663).

## Important Dependencies
- `osoji.config.Config` — project config; `root_path` used for file resolution.
- `osoji.evidence.BUILDERS`, `EVIDENCE_KINDS` — builder registry and kind registry under test.
- `osoji.evidence_builders.BuildContext` — context object passed to builders; also provides `scan_files()` / `scan_truncated()` (L619–622).
- `osoji.evidence_builders._match_in_quotes`, `_backticked_names` — internal helpers tested directly (L510, L547, L563).
- `osoji.evidence_builders._MAX_SCAN_FILES` — monkeypatched to 3 in truncation tests (L634, L654).
- `osoji.findings.Finding` — domain finding object.
- `osoji.evidence.Evidence` — used in `_with_scanner_meta` to build `scanner_metadata` evidence.
- `osoji.deadcode._clean_zero_reference` — tested for truncated-zero-sweep behavior (L647).
- `osoji.triage.Claim` — wraps a finding for downstream triage (L660).
- `temp_dir` — pytest fixture (assumed session/function-scoped path fixture, defined elsewhere).

## Architectural Notes
- Builders must never raise; return `[]` on insufficient data (enforced by `test_builders_never_raise_on_missing_file`).
- `FakeFacts` normalizes backslashes for Windows path compatibility (L45).
- `_with_scanner_meta` reconstructs a `Finding` by iterating over a fixed tuple of field names (L438–441) — field additions to `Finding` that aren't listed there would be silently dropped.
- Tests use real filesystem writes (`write` helper) combined with `temp_dir` fixture for I/O integration.
- The `config` fixture disables gitignore (`respect_gitignore=False`) to ensure scan corpus is predictable.
