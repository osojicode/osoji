# tests\test_findings_adapter.py
@source-hash: 02f1570f3233bde2
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:55Z

## Purpose
Test suite for `osoji.findings_adapter` — the bridge that converts legacy detector output types (`JunkFinding`, `ContractFinding`, `DocFinding`, debris dicts, and various "candidate" types) into unified `Finding` objects.

## Structure Overview

### Helper Factories (L23–86)
Four private fixture factories build minimal valid input objects with keyword overrides:
- `_junk(**over)` (L23–39): Creates `JunkFinding` with default `category="dead_symbol"`
- `_contract(**over)` (L42–57): Creates `ContractFinding` with default `finding_type="violation"`
- `_doc(**over)` (L60–71): Creates `DocFinding` with default `category="stale_content"`
- `_debris(**over)` (L74–86): Creates a raw `dict` representing a shadow-doc debris finding

Five additional factories for "candidate" types (V1-5a/b), defined inline at module level or within test sections:
- `_dc_candidate(**over)` (L329–345): `DeadCodeCandidate` with `GrepHit` list
- `_dp_candidate(**over)` (L348–363): `DeadParamCandidate` with `CallSite` list
- `_obligation(**over)` (L480–493): `ConfigObligation` (plumbing)
- `_orphan_candidate(**over)` (L496–507): `OrphanCandidate`
- `_dep_candidate(**over)` (L510–522): `DependencyCandidate`
- `_cicd_candidate(**over)` (L525–539): `CICDCandidate`

### Test Classes

**`TestJunkAdapter`** (L89–138): Tests `finding_from_junk()`.
- Verifies detector name format `"{producer}:{category}"` and `gap_type == "reachability"` for all 6 junk categories (L90–104)
- Checks backslash path normalization → forward slashes (L106–108)
- Verifies triage fields (`verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity`) are all `None` (L116–124)
- Validates `evidence[0]` is `scanner_metadata` kind carrying `remediation`, `confidence`, `confidence_source`, `metadata` payload (L126–135)

**`TestContractAdapter`** (L141–214): Tests `finding_from_contract()`.
- Verifies `detector == "obligations:obligation_{finding_type}"` and `gap_type == "contract"` (L142–158)
- `gap_type_for("obligation_violation")` and `gap_type_for("obligation_implicit_contract")` both return `"contract"` (L154–158)
- `path` comes from `consumer_file` (L160–162)
- `symbol` is `None` and lines are `None` when `value=None` (L164–167)
- `scanner_metadata` evidence carries `scan_needles` (literal value), `priority_paths` (consumer first, then producer), `severity`, `remediation`, `producer_file`, nested `evidence` dict (L169–214)
- Sentinel producer `"(no producer found)"` is dropped from `priority_paths` (L207–214)
- Grouped finding (value=None): needles come from `evidence["values"]`, priority_paths include all co-sharer files (L187–205)

**`TestDocAdapter`** (L217–244): Tests `finding_from_doc()`.
- All 4 doc categories map to `gap_type == "description"` (L218–225)
- `path` comes from the `doc_path` argument (L227–229)
- `observed_behavior` comes from `evidence` field of `DocFinding`; `symbol` and `line_start` are `None` (L231–235)
- `scanner_metadata` evidence carries `severity`, `remediation`, `search_terms`, `shadow_ref` (L237–244)

**`TestDebrisAdapter`** (L247–286): Tests `finding_from_debris()` and `findings_from_debris()`.
- Category-to-gap-type mapping: `dead_code→reachability`, `stale_comment/misleading_docstring/commented_out_code/expired_todo→description`, `latent_bug→uncategorized` (L248–262)
- Unknown categories fall back to `"uncategorized"` (L264–266)
- `source` field used as path (with normalization); `line_start`/`line_end` preserved (L268–271)
- `scanner_metadata` carries `severity`, `suggestion`, `cross_file_verification_needed` (L273–279)
- `valid=False` records are NOT filtered by the adapter (filtering is shadow.py's responsibility) (L281–286)

**`TestGapTypeTable`** (L289–323): Meta/coverage test.
- `_category_enum(tool)` (L303–307): Extracts category enum values from a tool dict's JSON schema.
- Verifies every emitted category (from `SUBMIT_SHADOW_DOC_TOOL`, `ANALYZE_DOCUMENT_TOOL`, and hard-coded junk set) is either in `CATEGORY_TO_GAP_TYPE` or is `"latent_bug"` (L309–316)
- `gap_type_for("latent_bug") == "uncategorized"` (L318–319)
- Confirms `"stale_comment"` appears in `SUBMIT_SHADOW_DOC_TOOL` schema (L321–323)

**`TestDeadCodeCandidateAdapter`** (L366–419): Tests `finding_from_dead_code_candidate()` (imported inline).
- `detector == "deadcode:dead_symbol"`, `gap_type == "reachability"`, `contract_source == "symbol declaration"` (L367–377)
- `scan_needles` = `[qualified_name, bare_name]` (deduplicated if bare name equals full name) (L379–394)
- `priority_paths` sorted by path (deduplicated grep hit files) (L379–387)
- `ast_proven=True` changes `scan` to `"ast"` and modifies `observed_behavior` (L396–404)
- Finding `id` is stable across line drift and ref_count changes (L406–419)

**`TestDeadParamCandidateAdapter`** (L422–474): Tests `finding_from_dead_param_candidate()` (imported inline).
- `symbol == "{function_name}.{param_name}"`, `contract_source == "function signature"`, lines both equal `param_line` (L423–432)
- `scan_needles` = `[param_name, bare_function_name, class_name_if_method]` (L434–449)
- `priority_paths` = source_path first, then unique call-site files, then importers (L451–460)
- Finding `id` differs for same param name in different functions (L462–467)
- Finding `id` stable under param_line drift (L469–474)

**`TestConfigObligationAdapter`** (L542–578): Tests `finding_from_config_obligation()`.
- `detector == "plumbing:unactuated_config"`, `gap_type == "reachability"`, `symbol == field_name` (L543–553)
- `scan_needles` = `[field_name, schema_name]`; empty `schema_name` omitted (L555–568)
- `scanner_metadata` carries `schema_name`, `field_name`, `line_start`, `obligation` (L570–578)

**`TestOrphanCandidateAdapter`** (L581–614): Tests `finding_from_orphan_candidate()`.
- `symbol == basename`, `line_start == 1`, `line_end is None` (L582–590)
- `scan_needles` = `[basename, stem, ...public_surface[:3]]`, capped at 5 total (L592–607)
- Backslash path normalization (L609–614)

**`TestDepCandidateAdapter`** (L617–649): Tests `finding_from_dep_candidate()`.
- `symbol == package_name`, `line_start == line_number`, `line_end is None` (L618–626)
- `scan_needles` = `[package_name, ...import_names]` (L628–634)
- `is_dev=True` changes wording in `contract_claim` (L636–640)
- `scanner_metadata` carries `package_name`, `import_names`, `is_dev` (L642–649)

**`TestCICDCandidateAdapter`** (L652–677): Tests `finding_from_cicd_candidate()`.
- `symbol == element_name`, lines from `line_start`/`line_end` (L653–661)
- `scan_needles` = `[element_name, ...basenames_of_missing_paths]` (L663–669)
- `element_content` and `full_file_content` NOT carried in metadata (L671–677)

## Key Contracts Verified
- Detector name format: `"{namespace}:{category}"` (varies by adapter)
- All adapters produce `Finding` with `evidence[0].kind == "scanner_metadata"`
- Triage fields (`verdict`, `confidence`) always `None` from adapters (set by triage stage)
- Path normalization: backslash → forward slash universally
- `findings_from_debris()` does not filter on `valid` field
- `CATEGORY_TO_GAP_TYPE` must cover all categories from both tool schemas

## Dependencies
- `osoji.findings_adapter`: Module under test — imports 6 public symbols + 6 candidate adapters imported inline
- `osoji.findings.Finding`: Result type
- `osoji.doc_analysis.DocFinding`, `osoji.junk.JunkFinding`, `osoji.obligations.ContractFinding`: Input types
- `osoji.tools.ANALYZE_DOCUMENT_TOOL`, `osoji.tools.SUBMIT_SHADOW_DOC_TOOL`: Tool schema dicts used for meta-test
- `osoji.deadcode.DeadCodeCandidate`, `osoji.deadcode.GrepHit`: Inline-imported
- `osoji.deadparam.DeadParamCandidate`, `osoji.deadparam.CallSite`: Inline-imported
- `osoji.plumbing.ConfigObligation`: Inline-imported
- `osoji.junk_orphan.OrphanCandidate`: Inline-imported
- `osoji.junk_deps.DependencyCandidate`: Inline-imported
- `osoji.junk_cicd.CICDCandidate`: Inline-imported