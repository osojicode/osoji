"""Tests for the incremental-audit verdict manifest (V1-9).

The manifest persists Triage verdicts keyed by finding id so a later
``osoji audit --incremental`` run can reuse them for findings whose
evidence fingerprint is unchanged. See concepts/incremental-audit.md.
"""

import json

import pytest

from osoji.audit_manifest import (
    MANIFEST_SCHEMA,
    VerdictSession,
    cache_from_verdicts,
    current_version,
    get_head_commit,
    load_manifest,
    merge_verdicts,
    write_manifest,
)
from osoji.claim_builder import CLAIM_BUILDER_SCHEMA_VERSION
from osoji.findings import Finding


def _finding(**overrides) -> Finding:
    base = dict(
        detector="deadcode:dead_symbol",
        gap_type="reachability",
        path="src/mod.py",
        line_start=10,
        line_end=20,
        symbol="helper",
        contract_source="function definition",
        contract_claim="helper is used",
        observed_behavior="no references found",
        verdict="confirmed",
        confidence=0.9,
        triage_reasoning="no callers anywhere",
        suggested_fix="remove helper",
        severity="warning",
        evidence_fingerprint="fp-1",
    )
    base.update(overrides)
    return Finding(**base)


def _entry(fp="fp-1", detector="deadcode:dead_symbol", verdict="confirmed") -> dict:
    return {
        "detector": detector,
        "evidence_fingerprint": fp,
        "verdict": verdict,
        "confidence": 0.9,
        "triage_reasoning": "r",
        "suggested_fix": "f",
        "severity": "warning",
        "contract_class": None,
    }


# -- version ----------------------------------------------------------------


def test_current_version_embeds_schema_and_impl_hash():
    version = current_version()

    assert version.startswith(f"{CLAIM_BUILDER_SCHEMA_VERSION}:")
    assert len(version) > len(CLAIM_BUILDER_SCHEMA_VERSION) + 1


# -- load / write round trip --------------------------------------------------


def test_write_then_load_round_trips(temp_dir):
    path = temp_dir / ".osoji" / "audit-manifest.json"
    verdicts = {"fid-1": _entry()}

    write_manifest(path, verdicts, commit="abc123", version="cb-3:deadbeef")
    loaded = load_manifest(path)

    assert loaded is not None
    assert loaded["schema"] == MANIFEST_SCHEMA
    assert loaded["audited_commit"] == "abc123"
    assert loaded["osoji_version"] == "cb-3:deadbeef"
    assert loaded["verdicts"] == verdicts


def test_load_missing_returns_none(temp_dir):
    assert load_manifest(temp_dir / "absent.json") is None


def test_load_corrupt_returns_none(temp_dir):
    path = temp_dir / "audit-manifest.json"
    path.write_text("{not json", encoding="utf-8")

    assert load_manifest(path) is None


def test_load_wrong_schema_returns_none(temp_dir):
    path = temp_dir / "audit-manifest.json"
    path.write_text(
        json.dumps({"schema": 999, "verdicts": {}}), encoding="utf-8"
    )

    assert load_manifest(path) is None


def test_load_non_dict_verdicts_returns_none(temp_dir):
    path = temp_dir / "audit-manifest.json"
    path.write_text(
        json.dumps({"schema": MANIFEST_SCHEMA, "verdicts": []}), encoding="utf-8"
    )

    assert load_manifest(path) is None


# -- cache construction -------------------------------------------------------


def test_cache_from_verdicts_keys_by_id_and_fingerprint():
    verdicts = {"fid-1": _entry(fp="fp-1"), "fid-2": _entry(fp="fp-2")}

    cache = cache_from_verdicts(verdicts)

    assert cache[("fid-1", "fp-1")] == verdicts["fid-1"]
    assert cache[("fid-2", "fp-2")] == verdicts["fid-2"]


def test_cache_from_verdicts_skips_entries_without_fingerprint():
    verdicts = {"fid-1": _entry(fp=None)}

    assert cache_from_verdicts(verdicts) == {}


# -- VerdictSession.harvest ---------------------------------------------------


def test_harvest_records_decided_finding():
    session = VerdictSession()
    finding = _finding()

    session.harvest([finding])

    entry = session.harvested[finding.id]
    assert entry["detector"] == "deadcode:dead_symbol"
    assert entry["evidence_fingerprint"] == "fp-1"
    assert entry["verdict"] == "confirmed"
    assert entry["confidence"] == 0.9
    assert entry["triage_reasoning"] == "no callers anywhere"
    assert entry["suggested_fix"] == "remove helper"
    assert entry["severity"] == "warning"
    assert session.claims_seen == 1
    assert session.cache_hits == 0


def test_harvest_skips_verdict_none():
    session = VerdictSession()

    session.harvest([_finding(verdict=None)])

    assert session.harvested == {}
    assert session.claims_seen == 1


def test_harvest_skips_fingerprint_none():
    session = VerdictSession()

    session.harvest([_finding(evidence_fingerprint=None)])

    assert session.harvested == {}
    assert session.claims_seen == 1


def test_harvest_counts_cache_hits():
    finding = _finding()
    session = VerdictSession(
        cache={(finding.id, "fp-1"): _entry()}
    )

    session.harvest([finding, _finding(symbol="other")])

    assert session.claims_seen == 2
    assert session.cache_hits == 1
    assert session.hit_rate == 0.5


def test_hit_rate_none_when_no_claims_seen():
    assert VerdictSession().hit_rate is None


# -- merge_verdicts -----------------------------------------------------------


def test_merge_replaces_ran_producer_entries():
    previous = {"old-dead": _entry(detector="deadcode:dead_symbol")}
    harvested = {"new-dead": _entry(detector="deadcode:dead_symbol")}

    merged = merge_verdicts(previous, harvested, ran_producers={"deadcode"})

    assert "old-dead" not in merged  # disappeared finding dropped
    assert "new-dead" in merged


def test_merge_keeps_non_ran_producer_entries():
    previous = {
        "old-dead": _entry(detector="deadcode:dead_symbol"),
        "old-doc": _entry(detector="doc:stale_content", fp="fp-9"),
    }
    harvested = {"new-dead": _entry(detector="deadcode:dead_symbol")}

    merged = merge_verdicts(previous, harvested, ran_producers={"deadcode"})

    assert merged["old-doc"] == previous["old-doc"]
    assert "old-dead" not in merged
    assert "new-dead" in merged


# -- git head -----------------------------------------------------------------


def test_get_head_commit_outside_repo_returns_none(temp_dir):
    assert get_head_commit(temp_dir) is None
