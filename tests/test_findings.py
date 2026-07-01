"""Tests for the unified Finding/Evidence schema (osoji.findings, osoji.evidence)."""

import json

from osoji.evidence import EVIDENCE_KINDS, Evidence
from osoji.findings import Finding, compute_finding_id


def _make_finding(**overrides) -> Finding:
    """Build a Finding with sensible defaults, overridable per test."""

    kwargs = dict(
        detector="deadcode:dead_symbol",
        gap_type="reachability",
        path="src/osoji/foo.py",
        line_start=10,
        line_end=20,
        symbol="old_func",
        contract_source="function",
        contract_claim="exported helper that should be used",
        observed_behavior="no references in any indexed file",
    )
    kwargs.update(overrides)
    return Finding(**kwargs)


class TestFindingId:
    def test_id_is_16_hex(self):
        f = _make_finding()
        assert isinstance(f.id, str)
        assert len(f.id) == 16
        int(f.id, 16)  # valid hex

    def test_id_stable_same_inputs(self):
        assert _make_finding().id == _make_finding().id

    def test_id_changes_with_detector(self):
        assert _make_finding().id != _make_finding(detector="deps:dead_dependency").id

    def test_id_changes_with_path(self):
        assert _make_finding().id != _make_finding(path="src/osoji/bar.py").id

    def test_id_changes_with_symbol(self):
        assert _make_finding().id != _make_finding(symbol="other_func").id

    def test_id_changes_with_claim(self):
        assert _make_finding().id != _make_finding(contract_claim="a different claim").id

    def test_line_numbers_do_not_change_id_when_symbol_present(self):
        # Anti-churn: inserting an import above shifts lines but must not bust the id.
        a = _make_finding(line_start=10, line_end=20)
        b = _make_finding(line_start=99, line_end=120)
        assert a.id == b.id

    def test_symbol_none_uses_line_fallback(self):
        # Symbol-less findings (debris) fall back to location for distinctness.
        a = _make_finding(symbol=None, line_start=10, line_end=12)
        b = _make_finding(symbol=None, line_start=40, line_end=42)
        assert a.id != b.id
        same = _make_finding(symbol=None, line_start=10, line_end=12)
        assert a.id == same.id

    def test_explicit_id_not_recomputed(self):
        f = _make_finding(id="deadbeefdeadbeef")
        assert f.id == "deadbeefdeadbeef"

    def test_none_location_deterministic(self):
        a = _make_finding(symbol=None, line_start=None, line_end=None)
        b = _make_finding(symbol=None, line_start=None, line_end=None)
        assert a.id == b.id

    def test_delimiter_safe(self):
        # A separator character inside one field must not collide with a
        # different field decomposition (json encoding makes parts unambiguous).
        a = compute_finding_id("d", "p", "sym", "claim")
        b = compute_finding_id("d", "p", 'sym","claim', "")
        assert a != b

    def test_evidence_fingerprint_not_in_id(self):
        a = _make_finding()
        b = _make_finding(evidence_fingerprint="abc123")
        assert a.id == b.id


class TestFindingSerialization:
    def test_round_trip_minimal(self):
        f = _make_finding()
        assert Finding.from_dict(f.to_dict()) == f

    def test_round_trip_with_evidence(self):
        ev = Evidence(kind="scanner_metadata", weight_hint=0.9, payload={"severity": "warning"})
        f = _make_finding(evidence=[ev])
        restored = Finding.from_dict(f.to_dict())
        assert restored == f
        assert isinstance(restored.evidence[0], Evidence)

    def test_id_survives_round_trip(self):
        f = _make_finding()
        assert Finding.from_dict(f.to_dict()).id == f.id

    def test_evidence_fingerprint_defaults_none(self):
        assert _make_finding().evidence_fingerprint is None

    def test_evidence_fingerprint_round_trips(self):
        f = _make_finding(evidence_fingerprint="fp-xyz")
        assert Finding.from_dict(f.to_dict()).evidence_fingerprint == "fp-xyz"

    def test_json_dumps_default_str(self):
        f = _make_finding(evidence=[Evidence(kind="ast_fact", payload={"k": "v"})])
        # Should not raise.
        json.dumps(f.to_dict(), default=str)

    def test_triage_fields_default_none(self):
        f = _make_finding()
        assert f.verdict is None
        assert f.confidence is None
        assert f.triage_reasoning is None
        assert f.suggested_fix is None
        assert f.severity is None


class TestGapType:
    def test_uncategorized_accepted(self):
        f = _make_finding(gap_type="uncategorized")
        assert f.gap_type == "uncategorized"

    def test_all_literal_values_accepted(self):
        for gt in ("reachability", "description", "contract", "uncategorized"):
            assert _make_finding(gap_type=gt).gap_type == gt


class TestEvidence:
    def test_round_trip(self):
        ev = Evidence(kind="cross_file_reference", weight_hint=0.5, payload={"file": "a.py"})
        assert Evidence.from_dict(ev.to_dict()) == ev

    def test_six_kinds_present(self):
        assert set(EVIDENCE_KINDS) == {
            "ast_fact",
            "cross_file_reference",
            "shadow_doc_claim",
            "scanner_metadata",
            "git_blame",
            "type_signature",
        }

    def test_empty_payload_round_trips(self):
        ev = Evidence(kind="git_blame")
        restored = Evidence.from_dict(ev.to_dict())
        assert restored == ev
        assert restored.payload == {}
