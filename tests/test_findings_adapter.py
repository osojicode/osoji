"""Tests for the legacy-detector -> Finding bridge (osoji.findings_adapter)."""

from pathlib import Path

import pytest

from osoji.doc_analysis import DocFinding
from osoji.findings import Finding
from osoji.findings_adapter import (
    CATEGORY_TO_GAP_TYPE,
    finding_from_contract,
    finding_from_debris,
    finding_from_doc,
    finding_from_junk,
    findings_from_debris,
    gap_type_for,
)
from osoji.junk import JunkFinding
from osoji.obligations import ContractFinding
from osoji.tools import ANALYZE_DOCUMENT_TOOL, SUBMIT_SHADOW_DOC_TOOL


def _junk(category="dead_symbol", **over) -> JunkFinding:
    kwargs = dict(
        source_path="src/osoji/foo.py",
        name="old_func",
        kind="function",
        category=category,
        line_start=10,
        line_end=20,
        confidence=0.9,
        reason="no references",
        remediation="remove it",
        original_purpose="exported helper",
        confidence_source="ast_proven",
        metadata={"extra": 1},
    )
    kwargs.update(over)
    return JunkFinding(**kwargs)


def _contract(finding_type="violation", **over) -> ContractFinding:
    kwargs = dict(
        finding_type=finding_type,
        contract_type="string_contract",
        value="failed",
        producer_file="src/osoji/a.py",
        consumer_file="src/osoji/b.py",
        definer_file=None,
        severity="warning",
        confidence=0.5,
        description="value 'failed' produced in a.py, checked in b.py",
        evidence={"value": "failed", "producer_context": "raise", "checker_context": "assert"},
        remediation="extract a shared constant",
    )
    kwargs.update(over)
    return ContractFinding(**kwargs)


def _doc(category="stale_content", **over) -> DocFinding:
    kwargs = dict(
        category=category,
        severity="warning",
        description="README claims stateless workers",
        shadow_ref="src/osoji/worker.py",
        evidence="worker.py caches per-request state",
        remediation="update the README",
        search_terms=["stateless", "worker"],
    )
    kwargs.update(over)
    return DocFinding(**kwargs)


def _debris(category="stale_comment", **over) -> dict:
    d = dict(
        source="src/osoji/foo.py",
        category=category,
        line_start=5,
        line_end=6,
        severity="warning",
        description="comment says sorted; code uses a set",
        suggestion="fix the comment",
        cross_file_verification_needed=False,
    )
    d.update(over)
    return d


class TestJunkAdapter:
    @pytest.mark.parametrize(
        "category,producer",
        [
            ("dead_symbol", "deadcode"),
            ("dead_parameter", "deadparam"),
            ("unactuated_config", "plumbing"),
            ("dead_dependency", "deps"),
            ("dead_cicd", "cicd"),
            ("orphaned_file", "orphan"),
        ],
    )
    def test_detector_name_and_reachability(self, category, producer):
        f = finding_from_junk(_junk(category=category))
        assert f.detector == f"{producer}:{category}"
        assert f.gap_type == "reachability"

    def test_path_normalized(self):
        f = finding_from_junk(_junk(source_path="src\\osoji\\foo.py"))
        assert f.path == "src/osoji/foo.py"

    def test_symbol_and_lines(self):
        f = finding_from_junk(_junk(line_end=None))
        assert f.symbol == "old_func"
        assert f.line_start == 10
        assert f.line_end is None

    def test_triage_fields_left_none(self):
        f = finding_from_junk(_junk())
        assert (f.verdict, f.confidence, f.triage_reasoning, f.suggested_fix, f.severity) == (
            None,
            None,
            None,
            None,
            None,
        )

    def test_priors_preserved_as_scanner_metadata_evidence(self):
        f = finding_from_junk(_junk())
        assert len(f.evidence) == 1
        ev = f.evidence[0]
        assert ev.kind == "scanner_metadata"
        assert ev.weight_hint == 0.9
        assert ev.payload["remediation"] == "remove it"
        assert ev.payload["confidence"] == 0.9
        assert ev.payload["confidence_source"] == "ast_proven"
        assert ev.payload["metadata"] == {"extra": 1}

    def test_returns_finding(self):
        assert isinstance(finding_from_junk(_junk()), Finding)


class TestContractAdapter:
    def test_violation_to_contract(self):
        # V1-5c: detector is prefixed so category_of matches the CLAIM_BUILDER_SCHEMA
        # obligation_* keys AND the persisted obligation_{finding_type} category.
        f = finding_from_contract(_contract(finding_type="violation"))
        assert f.detector == "obligations:obligation_violation"
        assert f.gap_type == "contract"

    def test_implicit_contract_to_contract(self):
        f = finding_from_contract(_contract(finding_type="implicit_contract"))
        assert f.detector == "obligations:obligation_implicit_contract"
        assert f.gap_type == "contract"

    def test_persisted_categories_route_to_contract(self):
        # The CE-gap fix: the persisted (prefixed) categories must map to the
        # contract gap, not the uncategorized outlet.
        assert gap_type_for("obligation_violation") == "contract"
        assert gap_type_for("obligation_implicit_contract") == "contract"

    def test_path_from_consumer_file(self):
        f = finding_from_contract(_contract())
        assert f.path == "src/osoji/b.py"

    def test_symbol_from_value_and_lines_none(self):
        f = finding_from_contract(_contract(value=None))
        assert f.symbol is None
        assert f.line_start is None and f.line_end is None

    def test_priors_preserved(self):
        f = finding_from_contract(_contract())
        ev = f.evidence[0]
        assert ev.kind == "scanner_metadata"
        assert ev.weight_hint == 0.5
        assert ev.payload["severity"] == "warning"
        assert ev.payload["remediation"] == "extract a shared constant"
        assert ev.payload["producer_file"] == "src/osoji/a.py"
        assert ev.payload["evidence"]["value"] == "failed"

    def test_scanner_metadata_carries_needles_and_priority(self):
        # Single-value finding: needle is the literal; priority paths are the
        # file tuple (consumer first, then producer), sentinel/None dropped.
        f = finding_from_contract(_contract())
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["failed"]
        assert meta.payload["priority_paths"] == ["src/osoji/b.py", "src/osoji/a.py"]

    def test_grouped_needles_and_sharers(self):
        # Grouped finding (value=None): needles come from evidence["values"] and
        # priority_paths includes every co-sharer file, not just the header pair.
        f = finding_from_contract(_contract(
            value=None,
            producer_file="src/osoji/prod.py",
            consumer_file="src/osoji/cons.py",
            evidence={
                "values": ["alpha", "beta"],
                "count": 2,
                "producer_files": ["src/osoji/prod.py", "src/osoji/prod2.py"],
                "checker_files": ["src/osoji/cons.py"],
                "definer_files": [],
            },
        ))
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["alpha", "beta"]
        assert "src/osoji/prod2.py" in meta.payload["priority_paths"]
        assert meta.payload["priority_paths"][0] == "src/osoji/cons.py"

    def test_violation_sentinel_producer_dropped_from_priority(self):
        f = finding_from_contract(_contract(
            finding_type="violation",
            producer_file="(no producer found)",
        ))
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert "(no producer found)" not in meta.payload["priority_paths"]
        assert meta.payload["priority_paths"] == ["src/osoji/b.py"]


class TestDocAdapter:
    @pytest.mark.parametrize(
        "category",
        ["stale_content", "incorrect_content", "obsolete_reference", "misleading_claim"],
    )
    def test_each_category_to_description(self, category):
        f = finding_from_doc(_doc(category=category), Path("docs/README.md"))
        assert f.detector == f"doc:{category}"
        assert f.gap_type == "description"

    def test_path_from_doc_path(self):
        f = finding_from_doc(_doc(), Path("docs/README.md"))
        assert f.path == "docs/README.md"

    def test_observed_from_evidence_quote(self):
        f = finding_from_doc(_doc(), "docs/README.md")
        assert f.observed_behavior == "worker.py caches per-request state"
        assert f.symbol is None
        assert f.line_start is None

    def test_priors_preserved(self):
        f = finding_from_doc(_doc(), "docs/README.md")
        ev = f.evidence[0]
        assert ev.kind == "scanner_metadata"
        assert ev.payload["severity"] == "warning"
        assert ev.payload["remediation"] == "update the README"
        assert ev.payload["search_terms"] == ["stateless", "worker"]
        assert ev.payload["shadow_ref"] == "src/osoji/worker.py"


class TestDebrisAdapter:
    @pytest.mark.parametrize(
        "category,gap",
        [
            ("dead_code", "reachability"),
            ("stale_comment", "description"),
            ("misleading_docstring", "description"),
            ("commented_out_code", "description"),
            ("expired_todo", "description"),
            ("latent_bug", "uncategorized"),
        ],
    )
    def test_each_category(self, category, gap):
        f = finding_from_debris(_debris(category=category))
        assert f.detector == f"debris:{category}"
        assert f.gap_type == gap

    def test_unknown_category_uncategorized(self):
        f = finding_from_debris(_debris(category="brand_new_kind"))
        assert f.gap_type == "uncategorized"

    def test_source_used_for_path_and_lines_preserved(self):
        f = finding_from_debris(_debris(source="src\\osoji\\foo.py", line_start=5, line_end=6))
        assert f.path == "src/osoji/foo.py"
        assert (f.line_start, f.line_end) == (5, 6)

    def test_priors_preserved(self):
        f = finding_from_debris(_debris(cross_file_verification_needed=True))
        ev = f.evidence[0]
        assert ev.kind == "scanner_metadata"
        assert ev.payload["severity"] == "warning"
        assert ev.payload["suggestion"] == "fix the comment"
        assert ev.payload["cross_file_verification_needed"] is True

    def test_no_valid_skip(self):
        # shadow.py filters valid:false at write time; the adapter must NOT
        # re-check it (phantom contract). A valid=False record still converts.
        items = [_debris(), _debris(valid=False)]
        result = findings_from_debris(items)
        assert len(result) == 2


class TestGapTypeTable:
    """Meta-test: every category any detector emits is classified or an
    intentional fallback. Catches a new tools.py enum value that forgets to
    update CATEGORY_TO_GAP_TYPE."""

    JUNK_CATEGORIES = {
        "dead_symbol",
        "dead_parameter",
        "unactuated_config",
        "dead_dependency",
        "dead_cicd",
        "orphaned_file",
    }

    @staticmethod
    def _category_enum(tool: dict) -> list[str]:
        return tool["input_schema"]["properties"]["findings"]["items"]["properties"]["category"][
            "enum"
        ]

    def test_all_emitted_categories_classified_or_intentional_fallback(self):
        debris = set(self._category_enum(SUBMIT_SHADOW_DOC_TOOL))
        docs = set(self._category_enum(ANALYZE_DOCUMENT_TOOL))
        emitted = debris | docs | self.JUNK_CATEGORIES
        for category in emitted:
            assert (
                category in CATEGORY_TO_GAP_TYPE or category == "latent_bug"
            ), f"category {category!r} is neither in CATEGORY_TO_GAP_TYPE nor the latent_bug fallback"

    def test_latent_bug_is_uncategorized(self):
        assert gap_type_for("latent_bug") == "uncategorized"

    def test_debris_categories_present(self):
        # Sanity-check our extraction path matches the known debris enum.
        assert "stale_comment" in self._category_enum(SUBMIT_SHADOW_DOC_TOOL)


# --- propose-time candidate adapters (V1-5a) ---------------------------------


def _dc_candidate(**over):
    from osoji.deadcode import DeadCodeCandidate, GrepHit

    kwargs = dict(
        source_path="src/osoji/foo.py",
        name="Widget.render",
        kind="method",
        line_start=40,
        line_end=44,
        ref_count=2,
        grep_hits=[
            GrepHit(file_path="src/osoji/b.py", line_number=3, context="w.render()"),
            GrepHit(file_path="src/osoji/a.py", line_number=9, context="# render"),
        ],
    )
    kwargs.update(over)
    return DeadCodeCandidate(**kwargs)


def _dp_candidate(**over):
    from osoji.deadparam import CallSite, DeadParamCandidate

    kwargs = dict(
        source_path="src/osoji/foo.py",
        function_name="Widget.render",
        param_name="verbose",
        param_line=40,
        has_default=True,
        call_sites=[
            CallSite(file_path="src/osoji/b.py", line_number=3, context="w.render()"),
            CallSite(file_path="src/osoji/b.py", line_number=8, context="w.render(1)"),
        ],
    )
    kwargs.update(over)
    return DeadParamCandidate(**kwargs)


class TestDeadCodeCandidateAdapter:
    def test_basic_mapping(self):
        from osoji.findings_adapter import finding_from_dead_code_candidate

        f = finding_from_dead_code_candidate(_dc_candidate())
        assert f.detector == "deadcode:dead_symbol"
        assert f.gap_type == "reachability"
        assert f.path == "src/osoji/foo.py"
        assert f.symbol == "Widget.render"
        assert f.contract_source == "symbol declaration"
        assert "`Widget.render` (method)" in f.contract_claim
        assert f.verdict is None and f.confidence is None

    def test_scanner_metadata_carries_needles_and_priority(self):
        from osoji.findings_adapter import finding_from_dead_code_candidate

        f = finding_from_dead_code_candidate(_dc_candidate())
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["Widget.render", "render"]
        assert meta.payload["priority_paths"] == ["src/osoji/a.py", "src/osoji/b.py"]
        assert meta.payload["scan"] == "grep"
        assert meta.payload["ref_count"] == 2

    def test_bare_name_needle_not_duplicated(self):
        from osoji.findings_adapter import finding_from_dead_code_candidate

        f = finding_from_dead_code_candidate(_dc_candidate(name="lonely", kind="function"))
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["lonely"]

    def test_ast_proven_changes_scan_and_observation(self):
        from osoji.findings_adapter import finding_from_dead_code_candidate

        f = finding_from_dead_code_candidate(
            _dc_candidate(ref_count=0, grep_hits=[]), ast_proven=True
        )
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan"] == "ast"
        assert "AST graph" in f.observed_behavior

    def test_id_stable_under_line_drift(self):
        from osoji.findings_adapter import finding_from_dead_code_candidate

        a = finding_from_dead_code_candidate(_dc_candidate(line_start=40, line_end=44))
        b = finding_from_dead_code_candidate(_dc_candidate(line_start=90, line_end=94))
        assert a.id == b.id

    def test_id_stable_across_ref_count_changes(self):
        # counts live in observed_behavior, never in the hashed contract_claim
        from osoji.findings_adapter import finding_from_dead_code_candidate

        a = finding_from_dead_code_candidate(_dc_candidate(ref_count=0, grep_hits=[]))
        b = finding_from_dead_code_candidate(_dc_candidate(ref_count=2))
        assert a.id == b.id


class TestDeadParamCandidateAdapter:
    def test_basic_mapping(self):
        from osoji.findings_adapter import finding_from_dead_param_candidate

        f = finding_from_dead_param_candidate(_dp_candidate())
        assert f.detector == "deadparam:dead_parameter"
        assert f.gap_type == "reachability"
        assert f.symbol == "Widget.render.verbose"
        assert f.contract_source == "function signature"
        assert f.line_start == f.line_end == 40
        assert "`verbose`" in f.contract_claim

    def test_needles_are_param_first_then_function_names(self):
        # The param needle carries the deciding evidence (gated branches,
        # absence at caller files -- the V1-4 bootstrap signal); function
        # needles add call-site visibility.
        from osoji.findings_adapter import finding_from_dead_param_candidate

        f = finding_from_dead_param_candidate(_dp_candidate())
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["verbose", "render", "Widget"]

    def test_plain_function_needles(self):
        from osoji.findings_adapter import finding_from_dead_param_candidate

        f = finding_from_dead_param_candidate(_dp_candidate(function_name="run"))
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["scan_needles"] == ["verbose", "run"]

    def test_priority_paths_source_then_call_sites_then_importers(self):
        from osoji.findings_adapter import finding_from_dead_param_candidate

        f = finding_from_dead_param_candidate(
            _dp_candidate(), importers=["src/osoji/b.py", "src/osoji/c.py"]
        )
        [meta] = [e for e in f.evidence if e.kind == "scanner_metadata"]
        assert meta.payload["priority_paths"] == [
            "src/osoji/foo.py", "src/osoji/b.py", "src/osoji/c.py",
        ]

    def test_same_param_name_different_functions_distinct_ids(self):
        from osoji.findings_adapter import finding_from_dead_param_candidate

        a = finding_from_dead_param_candidate(_dp_candidate(function_name="alpha"))
        b = finding_from_dead_param_candidate(_dp_candidate(function_name="beta"))
        assert a.id != b.id

    def test_id_stable_under_param_line_drift(self):
        from osoji.findings_adapter import finding_from_dead_param_candidate

        a = finding_from_dead_param_candidate(_dp_candidate(param_line=40))
        b = finding_from_dead_param_candidate(_dp_candidate(param_line=77))
        assert a.id == b.id
