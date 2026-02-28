"""Tests for StringContractChecker with ratio-based set algorithm."""

import json
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.facts import FactsDB
from docstar.obligations import (
    CONTRACT_CHECKERS,
    ContractChecker,
    ContractFinding,
    StringContractChecker,
    run_all_contract_checks,
)


# --- Helpers ---

def _write_facts(temp_dir: Path, source: str, facts: dict) -> None:
    """Write a .facts.json file for a given source path."""
    facts_dir = temp_dir / ".docstar" / "facts"
    facts_file = facts_dir / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "generated": "2025-01-01T00:00:00Z",
        "imports": [],
        "exports": [],
        "calls": [],
        "string_literals": [],
        **facts,
    }
    facts_file.write_text(json.dumps(data), encoding="utf-8")


def _make_config(tmp_path: Path) -> Config:
    return Config(root_path=tmp_path)


# --- Ratio-based algorithm tests ---

class TestRatioAlgorithm:
    def test_zero_match_set_skipped(self, tmp_path):
        """3 checked strings, 0 producers -> no violations (external contract)."""
        _write_facts(tmp_path, "src/handler.py", {
            "string_literals": [
                {"value": "ext_alpha", "context": "membership check", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "ext_beta", "context": "membership check", "line": 11, "kind": "identifier", "usage": "checked"},
                {"value": "ext_gamma", "context": "membership check", "line": 12, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_full_match_set(self, tmp_path):
        """3 checked, all produced -> no violations."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "dead_code", "context": "appended to results", "line": 42, "kind": "identifier", "usage": "produced"},
                {"value": "dead_plumbing", "context": "appended to results", "line": 55, "kind": "identifier", "usage": "produced"},
                {"value": "dead_deps", "context": "appended to results", "line": 68, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_code", "context": "membership test", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "dead_plumbing", "context": "membership test", "line": 11, "kind": "identifier", "usage": "checked"},
                {"value": "dead_deps", "context": "membership test", "line": 12, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_partial_match_flags_unmatched(self, tmp_path):
        """4 checked, 1 matches -> 3 violations with confidence=0.25."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "alpha", "context": "membership test", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "beta", "context": "membership test", "line": 11, "kind": "identifier", "usage": "checked"},
                {"value": "gamma", "context": "membership test", "line": 12, "kind": "identifier", "usage": "checked"},
                {"value": "delta", "context": "membership test", "line": 13, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged = {v.evidence["value"] for v in violations}
        assert flagged == {"beta", "gamma", "delta"}
        assert len(violations) == 3
        for v in violations:
            assert v.confidence == 0.25

    def test_single_string_set_zero_match_skipped(self, tmp_path):
        """1 checked, 0 producers -> skipped (zero-match, documented limitation)."""
        _write_facts(tmp_path, "src/handler.py", {
            "string_literals": [
                {"value": "orphan", "context": "equality check", "line": 5, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_skips_test_files(self, tmp_path):
        """Checked strings in test files should not be flagged."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "tests/test_foo.py", {
            "string_literals": [
                {"value": "alpha", "context": "assertion", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "beta", "context": "assertion", "line": 11, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0


class TestComparisonSource:
    def test_external_origin_via_import_skipped(self, tmp_path):
        """Checked string with comparison_source tracing to external package -> skipped."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/handler.py", {
            "imports": [
                {"source": "anthropic", "names": ["Client"]},
            ],
            "string_literals": [
                # "alpha" matches, so partial-match logic kicks in
                {"value": "alpha", "context": "check", "line": 10, "kind": "identifier", "usage": "checked"},
                # "tool_use" doesn't match, but comparison_source traces to external import
                {"value": "tool_use", "context": "check against API response", "line": 20, "kind": "identifier", "usage": "checked", "comparison_source": "Client.response.type"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged = {v.evidence["value"] for v in violations}
        assert "tool_use" not in flagged

    def test_internal_origin_not_falsely_excluded(self, tmp_path):
        """Checked string with comparison_source tracing to internal code -> evaluated normally."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "imports": [
                {"source": ".registry", "names": ["get_categories"]},
            ],
            "string_literals": [
                {"value": "alpha", "context": "membership test", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "beta_internal", "context": "membership test", "line": 11, "kind": "identifier", "usage": "checked", "comparison_source": "get_categories()"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged = {v.evidence["value"] for v in violations}
        # beta_internal has internal comparison_source — should still be flagged
        assert "beta_internal" in flagged

    def test_no_comparison_source_still_flagged(self, tmp_path):
        """Unmatched string without comparison_source is still flagged."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "alpha", "context": "membership test", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "orphan_val", "context": "membership test", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged = {v.evidence["value"] for v in violations}
        assert "orphan_val" in flagged


class TestIntegrationReproducer:
    """Integration test modeling the junk_sources bug pattern:
    registry produces certain category names, report checks different names.
    """

    def test_junk_sources_bug_pattern(self, tmp_path):
        # Registry produces category identifiers
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "dead_code", "context": "appended to junk results", "line": 42, "kind": "identifier", "usage": "produced"},
                {"value": "dead_plumbing", "context": "appended to junk results", "line": 55, "kind": "identifier", "usage": "produced"},
                {"value": "dead_deps", "context": "appended to junk results", "line": 68, "kind": "identifier", "usage": "produced"},
            ],
        })
        # Report checks against WRONG names (the bug) but also has one right name
        # so it's a partial match, not zero-match
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_code", "context": "membership test in junk_sources dict", "line": 99, "kind": "identifier", "usage": "checked"},
                {"value": "dead_symbol", "context": "membership test in junk_sources dict", "line": 100, "kind": "identifier", "usage": "checked"},
                {"value": "dead_dependency", "context": "membership test in junk_sources dict", "line": 101, "kind": "identifier", "usage": "checked"},
            ],
        })
        # Config defines the correct names as constants
        _write_facts(tmp_path, "src/config.py", {
            "string_literals": [
                {"value": "dead_code", "context": "analyzer name constant", "line": 5, "kind": "identifier", "usage": "defined"},
                {"value": "dead_plumbing", "context": "analyzer name constant", "line": 6, "kind": "identifier", "usage": "defined"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()

        # The wrong names should be flagged
        flagged_values = {v.evidence["value"] for v in violations}
        assert "dead_symbol" in flagged_values
        assert "dead_dependency" in flagged_values

        # The correct names should NOT be flagged
        assert "dead_code" not in flagged_values
        assert "dead_plumbing" not in flagged_values
        assert "dead_deps" not in flagged_values

        # All violations should be warnings
        for v in violations:
            assert v.severity == "warning"
            assert v.obligation_type == "string_contract"


# --- Fragility detection tests ---

class TestFragilityDetection:
    def test_fully_implicit_contract_detected(self, tmp_path):
        """Value produced in one file and checked in another with no definer -> flagged."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "my_category", "context": "appended to list", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "my_category", "context": "membership check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 1
        assert implicit[0].severity == "info"
        assert implicit[0].producer_file == "src/producer.py"
        assert implicit[0].consumer_file == "src/consumer.py"

    def test_robust_contract_not_flagged(self, tmp_path):
        """Both producer and checker import from definer -> not flagged."""
        _write_facts(tmp_path, "src/constants.py", {
            "string_literals": [
                {"value": "my_category", "context": "constant definition", "line": 5, "kind": "identifier", "usage": "defined"},
            ],
            "exports": [{"name": "MY_CATEGORY", "kind": "variable", "line": 5}],
        })
        _write_facts(tmp_path, "src/producer.py", {
            "imports": [{"source": ".constants", "names": ["MY_CATEGORY"]}],
            "string_literals": [
                {"value": "my_category", "context": "appended to list", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "imports": [{"source": ".constants", "names": ["MY_CATEGORY"]}],
            "string_literals": [
                {"value": "my_category", "context": "membership check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 0

    def test_partially_robust_flagged(self, tmp_path):
        """Only producer links to definer, checker doesn't -> flagged."""
        _write_facts(tmp_path, "src/constants.py", {
            "string_literals": [
                {"value": "my_category", "context": "constant definition", "line": 5, "kind": "identifier", "usage": "defined"},
            ],
            "exports": [{"name": "MY_CATEGORY", "kind": "variable", "line": 5}],
        })
        _write_facts(tmp_path, "src/producer.py", {
            "imports": [{"source": ".constants", "names": ["MY_CATEGORY"]}],
            "string_literals": [
                {"value": "my_category", "context": "appended to list", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "my_category", "context": "membership check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 1

    def test_same_file_contract_not_flagged(self, tmp_path):
        """Value produced and checked in same file -> not flagged."""
        _write_facts(tmp_path, "src/handler.py", {
            "string_literals": [
                {"value": "my_category", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
                {"value": "my_category", "context": "checked", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 0

    def test_grouping_works(self, tmp_path):
        """3 implicit values between same file pair -> 1 grouped finding."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "cat_alpha", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
                {"value": "cat_beta", "context": "produced", "line": 11, "kind": "identifier", "usage": "produced"},
                {"value": "cat_gamma", "context": "produced", "line": 12, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "cat_alpha", "context": "checked", "line": 20, "kind": "identifier", "usage": "checked"},
                {"value": "cat_beta", "context": "checked", "line": 21, "kind": "identifier", "usage": "checked"},
                {"value": "cat_gamma", "context": "checked", "line": 22, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 1
        assert implicit[0].value is None  # grouped
        assert implicit[0].evidence["count"] == 3
        assert implicit[0].confidence == 0.8  # min(0.9, 0.5 + 0.1 * 3)

    def test_test_files_included_for_fragility(self, tmp_path):
        """Test files ARE included as consumers for fragility detection (unlike violations)."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "my_category", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "tests/test_handler.py", {
            "string_literals": [
                {"value": "my_category", "context": "assertion", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 1
        assert implicit[0].consumer_file == "tests/test_handler.py"

    def test_common_short_strings_excluded(self, tmp_path):
        """Short strings and common strings are excluded from fragility detection."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "id", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
                {"value": "ok", "context": "produced", "line": 11, "kind": "identifier", "usage": "produced"},
                {"value": "ab", "context": "produced", "line": 12, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "id", "context": "checked", "line": 20, "kind": "identifier", "usage": "checked"},
                {"value": "ok", "context": "checked", "line": 21, "kind": "identifier", "usage": "checked"},
                {"value": "ab", "context": "checked", "line": 22, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        findings = checker.find_contracts()
        implicit = [f for f in findings if f.finding_type == "implicit_contract"]
        assert len(implicit) == 0


# --- Contract framework tests ---

class TestContractFramework:
    def test_registry_contains_string_checker(self):
        """Registry should contain StringContractChecker."""
        assert StringContractChecker in CONTRACT_CHECKERS

    def test_run_all_returns_findings(self, tmp_path):
        """run_all_contract_checks() returns a list of ContractFinding."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "my_category", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "my_category", "context": "checked", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        findings = run_all_contract_checks(db)
        assert isinstance(findings, list)
        assert all(isinstance(f, ContractFinding) for f in findings)

    def test_contract_finding_fields(self, tmp_path):
        """ContractFinding has correct fields."""
        _write_facts(tmp_path, "src/producer.py", {
            "string_literals": [
                {"value": "my_category", "context": "produced", "line": 10, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/consumer.py", {
            "string_literals": [
                {"value": "my_category", "context": "checked", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        findings = run_all_contract_checks(db)
        assert len(findings) > 0
        f = findings[0]
        assert hasattr(f, "finding_type")
        assert hasattr(f, "contract_type")
        assert hasattr(f, "producer_file")
        assert hasattr(f, "consumer_file")
        assert hasattr(f, "severity")
        assert hasattr(f, "confidence")
        assert hasattr(f, "description")
        assert hasattr(f, "evidence")
        assert hasattr(f, "remediation")
        assert f.contract_type == "string_contract"

    def test_string_checker_is_contract_checker(self, tmp_path):
        """StringContractChecker is a ContractChecker subclass."""
        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        assert isinstance(checker, ContractChecker)
        assert checker.contract_type == "string_contract"
        assert checker.description != ""
