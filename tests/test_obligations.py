"""Tests for StringContractChecker with synthetic facts data."""

import json
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.facts import FactsDB
from docstar.obligations import StringContractChecker


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


# --- Tests ---

class TestStringContractChecker:
    def test_no_violations_when_produced(self, tmp_path):
        """Checked string has matching producer -> no violation."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "dead_code", "context": "appended to results list", "line": 42, "kind": "identifier", "usage": "produced"},
                {"value": "dead_plumbing", "context": "appended to results list", "line": 55, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_code", "context": "membership test in set", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "dead_plumbing", "context": "membership test in set", "line": 11, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_violation_when_no_producer(self, tmp_path):
        """Checked string with no producer anywhere -> violation."""
        _write_facts(tmp_path, "src/registry.py", {
            "string_literals": [
                {"value": "dead_code", "context": "appended to results list", "line": 42, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_symbol", "context": "membership test in set", "line": 10, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 1
        assert violations[0].evidence["value"] == "dead_symbol"
        assert violations[0].obligation_type == "string_contract"
        assert violations[0].confidence == 0.8

    def test_no_violation_when_defined(self, tmp_path):
        """Checked string matched as 'defined' -> not flagged (low confidence)."""
        _write_facts(tmp_path, "src/config.py", {
            "string_literals": [
                {"value": "dead_code", "context": "constant assignment", "line": 5, "kind": "identifier", "usage": "defined"},
            ],
        })
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_code", "context": "membership test", "line": 10, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_skips_non_identifier_strings(self, tmp_path):
        """Non-identifier strings (messages, paths) should not be flagged."""
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "File not found", "context": "error message check", "line": 10, "kind": "message", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_skips_strings_with_spaces(self, tmp_path):
        """Strings with spaces are not plausible identifiers."""
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "some value with spaces", "context": "check", "line": 10, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0


class TestExclusions:
    def test_skips_json_schema_keywords(self, tmp_path):
        """JSON Schema vocabulary keywords should not be flagged."""
        _write_facts(tmp_path, "src/validate.py", {
            "string_literals": [
                {"value": "type", "context": "JSON Schema type check", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "properties", "context": "JSON Schema properties check", "line": 20, "kind": "identifier", "usage": "checked"},
                {"value": "required", "context": "JSON Schema required check", "line": 30, "kind": "identifier", "usage": "checked"},
                {"value": "items", "context": "JSON Schema items check", "line": 40, "kind": "identifier", "usage": "checked"},
                {"value": "enum", "context": "JSON Schema enum check", "line": 50, "kind": "identifier", "usage": "checked"},
                {"value": "minimum", "context": "JSON Schema minimum check", "line": 60, "kind": "identifier", "usage": "checked"},
                {"value": "maximum", "context": "JSON Schema maximum check", "line": 70, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_skips_tool_names(self, tmp_path):
        """LLM tool names from tools.py should not be flagged."""
        # Use a tool name we know exists: "submit_shadow_doc"
        _write_facts(tmp_path, "src/shadow.py", {
            "string_literals": [
                {"value": "submit_shadow_doc", "context": "tool_call.name check", "line": 235, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged_values = {v.evidence["value"] for v in violations}
        assert "submit_shadow_doc" not in flagged_values

    def test_skips_test_files(self, tmp_path):
        """Checked strings in test files should not be flagged."""
        _write_facts(tmp_path, "tests/test_foo.py", {
            "string_literals": [
                {"value": "some_unchecked_value", "context": "test assertion", "line": 10, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_skips_test_directory_nested(self, tmp_path):
        """Files under tests/ subdirectories should also be skipped."""
        _write_facts(tmp_path, "tests/unit/test_bar.py", {
            "string_literals": [
                {"value": "orphan", "context": "substring check on description", "line": 5, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        assert len(violations) == 0

    def test_real_violation_still_detected_with_exclusions(self, tmp_path):
        """Exclusions don't suppress real violations in production code."""
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
                {"value": "dead_symbol", "context": "membership check", "line": 10, "kind": "identifier", "usage": "checked"},
                {"value": "type", "context": "JSON Schema check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        checker = StringContractChecker(db)
        violations = checker.check()
        flagged_values = {v.evidence["value"] for v in violations}
        # "dead_symbol" should still be caught
        assert "dead_symbol" in flagged_values
        # "type" should be excluded as protocol keyword
        assert "type" not in flagged_values


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
        # Report checks against WRONG names (the bug)
        _write_facts(tmp_path, "src/report.py", {
            "string_literals": [
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
