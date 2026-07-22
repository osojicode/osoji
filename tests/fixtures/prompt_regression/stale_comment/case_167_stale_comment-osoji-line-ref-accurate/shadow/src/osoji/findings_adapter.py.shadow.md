# src\osoji\findings_adapter.py
@source-hash: 0b8e50ebf510d16e
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:18Z

## Purpose
Bridge module converting per-detector native output types to the unified `Finding` dataclass. Lives on the live audit path between detector outputs and the Claim Builder/Triage stages. All adapters are pure functions with no side effects.

## Design Rules (L10-22)
1. **Triage-output fields stay `None`**: `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity` are never populated — those belong to the Triage stage.
2. **Signal conservation**: Detector priors are attached as `Evidence(kind="scanner_metadata", ...)` rather than dropped. `Evidence` is hand-constructed (not via `EvidenceBuilder`).

## Key Constants

### `CATEGORY_TO_GAP_TYPE` (L57-82)
Dict mapping category strings to `GapType` literals (`"reachability"`, `"contract"`, `"description"`). Authoritative three-gap taxonomy. `"latent_bug"` is intentionally absent → falls to `"uncategorized"`. Categories include dead code variants, obligation types, and doc-analysis findings.

### `_JUNK_PRODUCER` (L85-92)
Maps junk category strings to their producer module name (e.g., `"dead_symbol"` → `"deadcode"`), used for constructing detector names in `"<producer>:<category>"` format.

### `_MAX_NEEDLES = 5` (L46)
Cap on scan needles stored in `scanner_metadata`. Matches Claim Builder's own `_MAX_NEEDLES` to keep metadata honest about what will actually be grepped.

## Public Adapter Functions

### `gap_type_for(category)` (L95-98)
Returns `GapType` for a category string, falling back to `"uncategorized"`. Used by all adapters internally and callable externally.

### `finding_from_junk(jf, *, root)` (L119-145)
Converts post-verification `JunkFinding` → `Finding`. Detector name built from `_JUNK_PRODUCER` lookup. Evidence carries `remediation`, `confidence`, `confidence_source`, `metadata`.

### `finding_from_dead_code_candidate(c, *, ast_proven, root)` (L148-208)
Converts propose-time `DeadCodeCandidate` → `Finding`. Runs *before* Triage. `ast_proven=True` changes `observed_behavior` and sets `scan="ast"` vs `scan="grep"`. `scan_needles` = qualified name + bare name; `priority_paths` = grep hit files. Detector: `"deadcode:dead_symbol"`.

### `finding_from_dead_param_candidate(c, importers, *, root)` (L211-274)
Converts `DeadParamCandidate` → `Finding`. Symbol is `"function.param"` format. Needles: bare param name first (deciding evidence), then function grep name, then class name if method. `priority_paths`: defining file + call-site files + importers (deduped). Detector: `"deadparam:dead_parameter"`.

### `finding_from_config_obligation(o, *, root)` (L289-341)
Converts `ConfigObligation` → `Finding`. Needles: field name first, then schema name. Framed in enforcement terms (not mere textual reference). Detector: `"plumbing:unactuated_config"`.

### `finding_from_orphan_candidate(c, *, root)` (L344-399)
Converts `OrphanCandidate` → `Finding`. Normalizes path to POSIX before extracting basename/stem (handles Windows paths on Linux). Needles: basename + stem + `public_surface` symbols. `priority_paths` empty (no known importers by construction). Detector: `"orphan:orphaned_file"`.

### `finding_from_dep_candidate(c, *, root)` (L402-449)
Converts `DependencyCandidate` → `Finding`. Needles: package name + resolved import names. `priority_paths` empty (zero-import candidate). Detector: `"deps:dead_dependency"`. Path from `c.manifest_path`.

### `finding_from_cicd_candidate(c, *, root)` (L452-501)
Converts `CICDCandidate` → `Finding`. Needles: element name + basenames of missing paths. `element_content` not stored (SurroundingCodeBuilder re-reads it). Detector: `"cicd:dead_cicd"`. Path from `c.cicd_file`.

### `finding_from_contract(cf, *, root)` (L504-561)
Converts `ContractFinding` → `Finding`. Detector: `"obligations:obligation_{cf.finding_type}"`. `scan_needles` = shared literal value(s); `priority_paths` = full file tuple (consumer/producer/definer + co-sharers), skipping `"(no producer found)"` sentinel. `gap_type` hardcoded to `"contract"`.

### `finding_from_doc(df, doc_path, *, root)` (L564-601)
Converts `DocFinding` → `Finding`. `doc_path` from enclosing `DocAnalysisResult.path`. Evidence `weight_hint=0.0` (no finding-level confidence). `scan_needles` = `df.search_terms` (doubles as mechanized replacement for deleted verify pass). Detector: `"doc:{df.category}"`.

### `finding_from_debris(d, *, root)` (L604-636)
Converts raw debris finding dict → `Finding`. Supports both `"source"` and `"source_path"` keys for path lookup. Evidence `weight_hint=0.0`. Both `contract_claim` and `observed_behavior` use `description` (known bridge limitation, L611).

### `findings_from_debris(items, *, root)` (L639-651)
Batch-converts list of raw debris dicts → list of Findings. No `valid` filtering (shadow.py drops `valid: false` at write time, so persisted records have no `valid` key).

## Internal Helpers

### `_norm_path(path, root)` (L101-116)
Normalizes path to project-relative forward-slash string. If `root` given and path is absolute, makes relative (ignores `ValueError` if not relative to root). Strips leading `./`.

### `_dedup_needles(names, *, cap)` (L277-286)
Order-preserving deduplication of non-empty needle strings, capped at `_MAX_NEEDLES` (default 5).

## Detector Name Convention (L21)
All detectors use `"<producer>:<category>"` format (e.g., `"deadcode:dead_symbol"`, `"doc:stale_comment"`). Stable 1:1 unit for V1-7 per-detector metrics.

## Key Dependencies
- `Evidence` from `.evidence` — hand-constructed with `kind="scanner_metadata"`
- `Finding`, `GapType` from `.findings`
- All native candidate/finding types imported under `TYPE_CHECKING` only (avoids import-time coupling)

## Architecture Notes
- All imports of native detector types are `TYPE_CHECKING`-only (L32-41); no runtime coupling to detector modules
- `root` parameter on all public adapters allows absolute paths from Windows-walked repos to be made project-relative
- `scan_needles` and `priority_paths` in evidence payloads steer `CrossFileReferenceBuilder` in the Claim Builder stage
