"""Tests for FactsDB with synthetic .facts.json data."""

import json
from pathlib import Path

import pytest

from osoji.config import Config
from osoji.facts import FactsDB


# --- Helpers ---

def _write_facts(temp_dir: Path, source: str, facts: dict) -> None:
    """Write a .facts.json file for a given source path."""
    facts_dir = temp_dir / ".osoji" / "facts"
    facts_file = facts_dir / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "generated": "2025-01-01T00:00:00Z",
        **facts,
    }
    facts_file.write_text(json.dumps(data), encoding="utf-8")


def _make_config(tmp_path: Path) -> Config:
    """Create a Config rooted at tmp_path."""
    return Config(root_path=tmp_path)


# --- Tests ---

class TestFactsDBLoading:
    def test_loads_all_files(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {"imports": [], "exports": [], "calls": [], "string_literals": []})
        _write_facts(tmp_path, "src/b.py", {"imports": [], "exports": [], "calls": [], "string_literals": []})
        _write_facts(tmp_path, "src/c.py", {"imports": [], "exports": [], "calls": [], "string_literals": []})

        db = FactsDB(_make_config(tmp_path))
        assert len(db.all_files()) == 3
        assert set(db.all_files()) == {"src/a.py", "src/b.py", "src/c.py"}

    def test_empty_facts_dir(self, tmp_path):
        db = FactsDB(_make_config(tmp_path))
        assert db.all_files() == []

    def test_get_file(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [{"source": ".b", "names": ["foo"], "is_reexport": False}],
            "exports": [{"name": "bar", "kind": "function", "line": 10}],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        facts = db.get_file("src/a.py")
        assert facts is not None
        assert facts.source == "src/a.py"
        assert len(facts.imports) == 1
        assert len(facts.exports) == 1

    def test_get_file_missing(self, tmp_path):
        db = FactsDB(_make_config(tmp_path))
        assert db.get_file("nonexistent.py") is None


class TestImportGraph:
    def test_imports_of(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [{"source": ".b", "names": ["foo"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [],
            "exports": [{"name": "foo", "kind": "function", "line": 1}],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        assert db.imports_of("src/a.py") == ["src/b.py"]
        assert db.imports_of("src/b.py") == []

    def test_importers_of(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [{"source": ".b", "names": ["foo"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [],
            "exports": [{"name": "foo", "kind": "function", "line": 1}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/c.py", {
            "imports": [{"source": ".b", "names": ["bar"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        importers = sorted(db.importers_of("src/b.py"))
        assert importers == ["src/a.py", "src/c.py"]

    def test_build_import_graph(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [{"source": ".b", "names": ["x"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [{"source": ".c", "names": ["y"], "is_reexport": False}],
            "exports": [{"name": "x", "kind": "function", "line": 1}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/c.py", {
            "imports": [],
            "exports": [{"name": "y", "kind": "class", "line": 5}],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        graph = db.build_import_graph()
        assert graph["src/a.py"] == {"src/b.py"}
        assert graph["src/b.py"] == {"src/c.py"}
        assert graph["src/c.py"] == set()


class TestExports:
    def test_exported_names(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [
                {"name": "foo", "kind": "function", "line": 1},
                {"name": "Bar", "kind": "class", "line": 10},
            ],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        assert db.exported_names("src/a.py") == {"foo", "Bar"}

    def test_unused_exports(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [
                {"name": "foo", "kind": "function", "line": 1},
                {"name": "bar", "kind": "function", "line": 10},
            ],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [{"source": ".a", "names": ["foo"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        unused = db.unused_exports()
        # "bar" from src/a.py is unused, "foo" is imported by src/b.py
        assert ("src/a.py", "bar") in unused
        assert ("src/a.py", "foo") not in unused


class TestStringLiterals:
    def test_strings_by_usage(self, tmp_path):
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "appended to results", "line": 5, "kind": "identifier", "usage": "produced"},
                {"value": "debug_mode", "context": "config key", "line": 10, "kind": "config", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "checked in set", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))

        produced = db.strings_by_usage("produced", kind="identifier")
        assert "dead_code" in produced.get("src/a.py", set())

        checked = db.strings_by_usage("checked", kind="identifier")
        assert "dead_code" in checked.get("src/b.py", set())

    def test_string_contract_match(self, tmp_path):
        """A produces 'dead_code', B checks 'dead_code' -> no violation expected."""
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "appended to results", "line": 5, "kind": "identifier", "usage": "produced"},
            ],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "membership check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        # Verify data is loaded
        produced = db.strings_by_usage("produced", kind="identifier")
        checked = db.strings_by_usage("checked", kind="identifier")
        # Both should have "dead_code"
        assert "dead_code" in produced.get("src/a.py", set())
        assert "dead_code" in checked.get("src/b.py", set())

    def test_defined_only_match(self, tmp_path):
        """A defines 'dead_code' (not produced), B checks 'dead_code' -> low confidence."""
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "assigned to constant", "line": 5, "kind": "identifier", "usage": "defined"},
            ],
        })
        _write_facts(tmp_path, "src/b.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                {"value": "dead_code", "context": "membership check", "line": 20, "kind": "identifier", "usage": "checked"},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        defined = db.strings_by_usage("defined", kind="identifier")
        assert "dead_code" in defined.get("src/a.py", set())


class TestCrossFileReferences:
    """Tests for FactsDB.cross_file_references()."""

    def test_finds_import_reference(self, tmp_path):
        """Detects when another file imports the symbol."""
        _write_facts(tmp_path, "src/scorecard.py", {
            "imports": [],
            "exports": [{"name": "Scorecard", "kind": "class", "line": 10}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/audit.py", {
            "imports": [{"source": ".scorecard", "names": ["Scorecard"], "is_reexport": False}],
            "exports": [],
            "calls": [],
            "string_literals": [],
        })
        db = FactsDB(_make_config(tmp_path))
        refs = db.cross_file_references("Scorecard", "src/scorecard.py")
        assert len(refs) >= 1
        import_refs = [r for r in refs if r["kind"] == "import"]
        assert len(import_refs) == 1
        assert import_refs[0]["file"] == "src/audit.py"

    def test_finds_call_reference(self, tmp_path):
        """Detects when another file calls the symbol."""
        _write_facts(tmp_path, "src/scorecard.py", {
            "imports": [],
            "exports": [{"name": "build_scorecard", "kind": "function", "line": 10}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/audit.py", {
            "imports": [],
            "exports": [],
            "calls": [{"to": "build_scorecard", "line": 50}],
            "string_literals": [],
        })
        db = FactsDB(_make_config(tmp_path))
        refs = db.cross_file_references("build_scorecard", "src/scorecard.py")
        call_refs = [r for r in refs if r["kind"] == "call"]
        assert len(call_refs) == 1
        assert call_refs[0]["file"] == "src/audit.py"

    def test_finds_qualified_call(self, tmp_path):
        """Detects qualified calls like module.symbol."""
        _write_facts(tmp_path, "src/scorecard.py", {
            "imports": [],
            "exports": [{"name": "obligation_violations", "kind": "variable", "line": 66}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/audit.py", {
            "imports": [],
            "exports": [],
            "calls": [{"to": "scorecard.obligation_violations", "line": 397}],
            "string_literals": [],
        })
        db = FactsDB(_make_config(tmp_path))
        refs = db.cross_file_references("obligation_violations", "src/scorecard.py")
        call_refs = [r for r in refs if r["kind"] == "call"]
        assert len(call_refs) == 1

    def test_excludes_same_file(self, tmp_path):
        """Does not include references from the defining file itself."""
        _write_facts(tmp_path, "src/scorecard.py", {
            "imports": [],
            "exports": [{"name": "Scorecard", "kind": "class", "line": 10}],
            "calls": [{"to": "Scorecard", "line": 200}],
            "string_literals": [],
        })
        db = FactsDB(_make_config(tmp_path))
        refs = db.cross_file_references("Scorecard", "src/scorecard.py")
        assert len(refs) == 0

    def test_no_references(self, tmp_path):
        """Returns empty list when no cross-file references exist."""
        _write_facts(tmp_path, "src/scorecard.py", {
            "imports": [],
            "exports": [{"name": "orphan_func", "kind": "function", "line": 10}],
            "calls": [],
            "string_literals": [],
        })
        _write_facts(tmp_path, "src/other.py", {
            "imports": [],
            "exports": [],
            "calls": [{"to": "unrelated_func", "line": 5}],
            "string_literals": [],
        })
        db = FactsDB(_make_config(tmp_path))
        refs = db.cross_file_references("orphan_func", "src/scorecard.py")
        assert refs == []


class TestMalformedEntries:
    """Ensure non-dict entries in list fields are silently filtered out."""

    def test_string_literals_plain_strings_filtered(self, tmp_path):
        """string_literals containing plain strings are silently dropped."""
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": ["foo", "bar"],
        })

        db = FactsDB(_make_config(tmp_path))
        facts = db.get_file("src/a.py")
        assert facts is not None
        assert facts.string_literals == []

    def test_string_literals_mixed_types_filtered(self, tmp_path):
        """Only dict entries survive when string_literals has mixed types."""
        _write_facts(tmp_path, "src/a.py", {
            "imports": [],
            "exports": [],
            "calls": [],
            "string_literals": [
                "plain_string",
                {"value": "good", "usage": "produced", "kind": "identifier", "context": "ok", "line": 1},
                42,
                {"value": "also_good", "usage": "checked", "kind": "config", "context": "ok", "line": 2},
            ],
        })

        db = FactsDB(_make_config(tmp_path))
        facts = db.get_file("src/a.py")
        assert facts is not None
        assert len(facts.string_literals) == 2
        assert facts.string_literals[0]["value"] == "good"
        assert facts.string_literals[1]["value"] == "also_good"

    def test_all_list_fields_filter_non_dicts(self, tmp_path):
        """imports, exports, and calls also filter out non-dict entries."""
        _write_facts(tmp_path, "src/a.py", {
            "imports": ["bad_import", {"source": ".b", "names": ["x"], "is_reexport": False}],
            "exports": [99, {"name": "foo", "kind": "function", "line": 1}],
            "calls": [None, {"target": "print", "line": 5}],
            "string_literals": [],
        })

        db = FactsDB(_make_config(tmp_path))
        facts = db.get_file("src/a.py")
        assert facts is not None
        assert len(facts.imports) == 1
        assert facts.imports[0]["source"] == ".b"
        assert len(facts.exports) == 1
        assert facts.exports[0]["name"] == "foo"
        assert len(facts.calls) == 1
        assert facts.calls[0]["target"] == "print"
