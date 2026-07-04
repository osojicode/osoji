"""Tests for the Claim Builder (V1-4 mechanized; V1-3 debris wrapper preserved).

build_claims is the generalized schema-as-config pass: per finding category a
SchemaEntry names the evidence kinds to build (in order) and the require_any
sufficiency gate; the assembled bundle gets a deterministic evidence_fingerprint
(schema version + impl hash + canonical bundle). build_debris_claims is now a
thin wrapper preserving the V1-3 debris contract exactly: only eligible findings
(dead_code / latent_bug always; stale_comment when flagged for cross-file check)
with satisfiable evidence become Claims; the rest pass through untouched.
Eligible-but-insufficient findings are *counted* (would_escalate) for the
escalation-rate baseline but never escalated here.
"""

import time
from dataclasses import replace

import pytest

from osoji.claim_builder import (
    CLAIM_BUILDER_SCHEMA,
    CLAIM_BUILDER_SCHEMA_VERSION,
    DEFAULT_SCHEMA_BY_GAP_TYPE,
    SchemaEntry,
    _extract_all_symbols_from_debris,
    build_claims,
    build_debris_claims,
    compute_evidence_fingerprint,
)
from osoji.config import Config
from osoji.evidence import BUILDERS, Evidence
from osoji.evidence_builders import BuildContext
from osoji.findings import Finding


# --- symbol extraction: ReDoS guard + behavior preservation ----------------


def test_pascalcase_extraction_is_redos_safe():
    # The PascalCase pass is fed LLM-generated text. A pathological "AaAa…A"
    # input (the kind that made the old nested-quantifier pattern backtrack
    # catastrophically) must resolve in linear time, not hang.
    pathological = "Aa" * 5000 + "A"
    start = time.monotonic()
    result = _extract_all_symbols_from_debris(pathological)
    assert time.monotonic() - start < 1.0
    assert result == [pathological]  # one word: starts [A-Z][a-z], many segments


@pytest.mark.parametrize(
    "description, expected_present",
    [
        ("source_path attribute of JunkFinding is never read", "JunkFinding"),
        ("`source_path` may not exist on JunkAnalysisResult", "JunkAnalysisResult"),
        ("SHADOW_DIR constant is unused", "SHADOW_DIR"),  # via fallback, not PascalCase
    ],
)
def test_pascalcase_extraction_preserves_behavior(description, expected_present):
    assert expected_present in _extract_all_symbols_from_debris(description)


def test_pascalcase_no_duplicates_preserved():
    # Backtick + plain-text occurrences of the same compound collapse to one.
    desc = "`CompletionOptions` type CompletionOptions has no field"
    symbols = _extract_all_symbols_from_debris(desc)
    assert symbols.count("CompletionOptions") == 1


def test_all_caps_is_not_pascalcase():
    # ALL_CAPS must not be picked up by the PascalCase predicate.
    assert "ABCDEF" not in _extract_all_symbols_from_debris("token ABCDEF here Aa")


@pytest.fixture
def config(temp_dir):
    return Config(root_path=temp_dir, respect_gitignore=False)


class FakeFacts:
    """Stand-in FactsDB exposing only cross_file_references."""

    def __init__(self, refs_by_symbol=None):
        self._refs = refs_by_symbol or {}

    def cross_file_references(self, symbol, source_path):
        return self._refs.get(symbol, [])


def debris(**over):
    d = dict(
        source="src/x.py",
        category="dead_code",
        line_start=10,
        line_end=12,
        severity="warning",
        description="`old_helper` is defined but never used",
        suggestion="remove it",
    )
    d.update(over)
    return d


def test_eligible_with_refs_becomes_claim_with_evidence(config):
    facts = FakeFacts({"old_helper": [
        {"file": "src/y.py", "kind": "import", "context": "from x import old_helper", "resolves_to_source": True},
    ]})
    claims, original_indices, would_escalate = build_debris_claims(
        config, [debris()], facts_db=facts, symbols_by_file={}
    )
    assert len(claims) == 1
    assert original_indices == [0]
    assert would_escalate == 0
    kinds = [e.kind for e in claims[0].finding.evidence]
    assert "cross_file_reference" in kinds
    xref = next(e for e in claims[0].finding.evidence if e.kind == "cross_file_reference")
    assert xref.payload["references"][0]["file"] == "src/y.py"


def test_ineligible_finding_is_not_a_claim(config):
    facts = FakeFacts()
    # stale_comment without the cross-file flag is ineligible (kept unverified)
    claims, original_indices, would_escalate = build_debris_claims(
        config, [debris(category="stale_comment", description="comment is stale")],
        facts_db=facts, symbols_by_file={},
    )
    assert claims == []
    assert original_indices == []
    assert would_escalate == 0


def test_stale_comment_with_flag_is_eligible(config):
    facts = FakeFacts({"thing": [
        {"file": "src/z.py", "kind": "call", "context": "thing()", "resolves_to_source": False},
    ]})
    claims, original_indices, _ = build_debris_claims(
        config,
        [debris(category="stale_comment", description="`thing` no longer does X",
                cross_file_verification_needed=True)],
        facts_db=facts, symbols_by_file={},
    )
    assert len(claims) == 1


def test_eligible_without_evidence_counts_as_would_escalate(config):
    facts = FakeFacts()  # no refs for anything
    claims, original_indices, would_escalate = build_debris_claims(
        config, [debris()], facts_db=facts, symbols_by_file={}
    )
    assert claims == []
    assert original_indices == []
    assert would_escalate == 1


def test_original_index_mapping_skips_non_candidates(config):
    facts = FakeFacts({"old_helper": [
        {"file": "src/y.py", "kind": "import", "context": "import", "resolves_to_source": True},
    ]})
    raw = [
        debris(category="commented_out_code", description="dead block"),  # ineligible
        debris(),                                                          # eligible + refs
    ]
    claims, original_indices, _ = build_debris_claims(
        config, raw, facts_db=facts, symbols_by_file={}
    )
    assert len(claims) == 1
    assert original_indices == [1]


def test_debris_wrapper_sets_fingerprint(config):
    facts = FakeFacts({"old_helper": [
        {"file": "src/y.py", "kind": "import", "context": "import", "resolves_to_source": True},
    ]})
    claims, _, _ = build_debris_claims(config, [debris()], facts_db=facts, symbols_by_file={})
    assert claims[0].finding.evidence_fingerprint is not None


def test_debris_latent_bug_type_defs_alone_suffice(config, temp_dir):
    # Legacy OR semantics: refs OR type definitions make a latent_bug claim.
    models = temp_dir / "src" / "models.py"
    models.parent.mkdir(parents=True, exist_ok=True)
    models.write_text("class CompletionOptions:\n    temperature: float = 0.0\n", encoding="utf-8")
    symbols = {"src/models.py": [
        {"name": "CompletionOptions", "kind": "class", "line_start": 1, "line_end": 2},
    ]}
    raw = [debris(
        category="latent_bug",
        description="`CompletionOptions` has no field `top_k`",
    )]
    claims, _, would_escalate = build_debris_claims(
        config, raw, facts_db=FakeFacts(), symbols_by_file=symbols
    )
    assert would_escalate == 0
    assert len(claims) == 1
    assert "type_signature" in [e.kind for e in claims[0].finding.evidence]


# --- generalized build_claims (V1-4) ----------------------------------------


def make_finding(**over):
    base = dict(
        detector="debris:dead_code",
        gap_type="reachability",
        path="src/x.py",
        line_start=1,
        line_end=2,
        symbol="old_helper",
        contract_source="symbol declaration",
        contract_claim="Symbol `old_helper` is declared but appears unused",
        observed_behavior="No callers or importers found",
    )
    base.update(over)
    return Finding(**base)


def populate(temp_dir):
    (temp_dir / "src").mkdir(parents=True, exist_ok=True)
    (temp_dir / "src" / "x.py").write_text(
        "def old_helper():\n    return 1\n", encoding="utf-8"
    )
    (temp_dir / "src" / "y.py").write_text(
        "from x import old_helper\nold_helper()\n", encoding="utf-8"
    )


def test_build_claims_sets_fingerprint_and_evidence(config, temp_dir):
    populate(temp_dir)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    claims = build_claims([make_finding()], ctx)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.insufficient_evidence is False
    kinds = {e.kind for e in claim.finding.evidence}
    assert "cross_file_reference" in kinds
    assert "surrounding_code" in kinds
    assert claim.finding.evidence_fingerprint is not None


def test_build_claims_empty_bundle_leaves_fingerprint_none(config):
    # Empty root, empty facts: nothing gatherable. A fingerprint over an empty
    # bundle would let colliding-id findings share a cache entry — keep it
    # None (cache-ineligible, decision 0014).
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    claims = build_claims([make_finding()], ctx)
    assert claims[0].insufficient_evidence is True
    assert claims[0].finding.evidence_fingerprint is None


def test_build_claims_uses_category_schema(config, temp_dir):
    populate(temp_dir)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        detector="debris:stale_comment", gap_type="description",
        symbol=None, contract_claim="comment says `old_helper` handles retries",
        observed_behavior="it does not",
    )
    claims = build_claims([finding], ctx)
    # description schema requires surrounding_code — met by the real file.
    assert claims[0].insufficient_evidence is False
    kinds = {e.kind for e in claims[0].finding.evidence}
    assert "surrounding_code" in kinds


def test_build_claims_falls_back_to_gap_type_default(config, temp_dir):
    populate(temp_dir)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(detector="scanner:novel_check")  # unknown category
    claims = build_claims([finding], ctx)
    assert claims[0].insufficient_evidence is False  # reachability default applied
    kinds = {e.kind for e in claims[0].finding.evidence}
    assert kinds <= set(DEFAULT_SCHEMA_BY_GAP_TYPE["reachability"].kinds)


def test_require_any_unmet_sets_insufficient_evidence(config, temp_dir):
    # Corpus exists but the claim text yields no needles: the reference builder
    # cannot even scan -> require_any={cross_file_reference} unmet.
    populate(temp_dir)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        symbol=None, contract_claim="the and but not", observed_behavior="was were has"
    )
    claims = build_claims([finding], ctx)
    assert claims[0].insufficient_evidence is True


def test_preexisting_evidence_is_preserved(config, temp_dir):
    populate(temp_dir)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    seeded = make_finding(evidence=[Evidence(kind="scanner_metadata", payload={"severity": "info"})])
    claims = build_claims([seeded], ctx)
    kinds = [e.kind for e in claims[0].finding.evidence]
    assert kinds[0] == "scanner_metadata"  # original evidence stays first


# --- evidence fingerprint ----------------------------------------------------


def _bundle():
    return [
        Evidence(kind="cross_file_reference", payload={"references": [{"file": "a.py"}]}),
        Evidence(kind="surrounding_code", payload={"file": "b.py", "snippet": "1: x"}),
    ]


def test_fingerprint_same_bundle_same_hash():
    assert compute_evidence_fingerprint(_bundle()) == compute_evidence_fingerprint(_bundle())


def test_fingerprint_is_order_insensitive():
    bundle = _bundle()
    assert compute_evidence_fingerprint(bundle) == compute_evidence_fingerprint(
        list(reversed(bundle))
    )


def test_fingerprint_changes_when_payload_changes():
    changed = [
        replace(_bundle()[0], payload={"references": [{"file": "OTHER.py"}]}),
        _bundle()[1],
    ]
    assert compute_evidence_fingerprint(_bundle()) != compute_evidence_fingerprint(changed)


def test_fingerprint_changes_with_schema_version():
    assert compute_evidence_fingerprint(_bundle()) != compute_evidence_fingerprint(
        _bundle(), schema_version="cb-TEST"
    )


def test_fingerprint_changes_with_impl_hash(monkeypatch):
    import osoji.claim_builder as cb

    before = compute_evidence_fingerprint(_bundle())
    monkeypatch.setattr(cb, "compute_impl_hash", lambda: "deadbeefdeadbeef")
    after = compute_evidence_fingerprint(_bundle())
    assert before != after


# --- schema configuration ----------------------------------------------------


def test_schema_entry_json_round_trip():
    entry = SchemaEntry(
        kinds=("cross_file_reference", "surrounding_code"),
        require_any=frozenset({"cross_file_reference"}),
    )
    assert SchemaEntry.from_dict(entry.to_dict()) == entry


def test_schema_version_is_pinned():
    # Growing EVIDENCE_KINDS or changing the schema tables/builders bumps this.
    # cb-2 (V1-5a): CrossFileReferenceBuilder honors scanner-supplied
    # scan_needles/priority_paths and flags in-string-literal hits.
    assert CLAIM_BUILDER_SCHEMA_VERSION == "cb-2"


def test_every_schema_kind_has_registered_builder():
    entries = list(CLAIM_BUILDER_SCHEMA.values()) + list(DEFAULT_SCHEMA_BY_GAP_TYPE.values())
    for entry in entries:
        for kind in entry.kinds:
            assert kind in BUILDERS, f"schema names unbuildable kind {kind}"
        assert set(entry.require_any) <= set(entry.kinds)
