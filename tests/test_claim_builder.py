"""Tests for the inline debris Claim Builder (V1-3).

build_debris_claims is the V1-3 stand-in for V1-4's mechanized Claim Builder. It
preserves today's debris-verify candidate selection exactly: only eligible
findings (dead_code / latent_bug always; stale_comment when flagged for
cross-file check) that have gatherable cross-file evidence become Claims; the
rest pass through untouched. Eligible-but-unfillable findings are *counted*
(would_escalate) for the V1-4 escalation-rate baseline but never escalated here.
"""

import pytest

from osoji.claim_builder import build_debris_claims
from osoji.config import Config


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
