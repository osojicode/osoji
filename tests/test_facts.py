"""Tests for FactsDB with synthetic .facts.json data."""

import json
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.facts import FactsDB


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
