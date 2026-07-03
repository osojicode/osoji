"""Offline tests for the V1-4 bootstrap harness (scripts/triage_bootstrap.py).

CI has no ``.osoji`` corpus (gitignored), so these tests exercise only the
fixture-origin manifest entries, whose facts/symbols sidecars are committed
under ``tests/fixtures/prompt_regression/<case>/``. No LLM, no network.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_PATH = REPO_ROOT / "scripts" / "triage_bootstrap.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("triage_bootstrap", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest(harness):
    return harness.load_manifest(harness.DEFAULT_MANIFEST)


def test_manifest_loads_and_validates(manifest):
    assert len(manifest["entries"]) == 54


def test_build_mode_fills_evidence_for_fixture_entries(harness, manifest):
    entries = [e for e in manifest["entries"] if e.get("origin") == "fixture"]
    assert entries, "manifest has no fixture entries"
    claims, meta = harness.build_claims_for_entries(entries)
    assert len(claims) == len(entries)
    insufficient = [m["slug"] for m in meta if m["insufficient"]]
    # The zero-LLM gate: fixture snapshots must be buildable, or ablation
    # would blow through the 5% threshold on builder gaps instead of verdicts.
    assert insufficient == []
    for claim in claims:
        assert claim.finding.evidence, claim.finding.id
        assert claim.finding.evidence_fingerprint is not None


def test_fixture_entry_paths_are_prefix_stripped(harness, manifest):
    entries = [e for e in manifest["entries"] if e.get("origin") == "fixture"][:1]
    claims, _ = harness.build_claims_for_entries(entries)
    assert not claims[0].finding.path.startswith("tests/fixtures")


def test_build_meta_reports_filled_kinds(harness, manifest):
    entries = [e for e in manifest["entries"] if e.get("origin") == "fixture"][:1]
    _, meta = harness.build_claims_for_entries(entries)
    assert meta[0]["slug"] == entries[0]["slug"]
    assert isinstance(meta[0]["kinds"], list)
    assert meta[0]["kinds"], "no evidence kinds recorded"
