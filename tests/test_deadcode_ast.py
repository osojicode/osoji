"""Tests for the AST fast path in dead code detection."""

import json
from unittest.mock import MagicMock, patch

import pytest

from osoji.config import Config, SHADOW_DIR
from osoji.facts import FactsDB
from osoji.deadcode import _all_importers_ast_extracted, _group_symbols_by_file
from osoji.junk import JunkFinding


def _make_config(tmp_path):
    config = MagicMock(spec=Config)
    config.root_path = tmp_path
    config.shadow_root = tmp_path / SHADOW_DIR
    return config


def _write_facts(tmp_path, source, extraction_method=None, imports=None, exports=None, calls=None):
    facts_dir = tmp_path / SHADOW_DIR / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "imports": imports or [],
        "exports": exports or [],
        "calls": calls or [],
        "member_writes": [],
        "string_literals": [],
    }
    if extraction_method is not None:
        data["extraction_method"] = extraction_method
    # Store with forward-slash-safe filename
    safe_name = source.replace("/", "__")
    (facts_dir / f"{safe_name}.facts.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_all_importers_ast_extracted_true(tmp_path):
    """Returns True when all importers have AST-extracted facts."""
    _write_facts(tmp_path, "lib.py", "ast", exports=[{"name": "helper", "kind": "function"}])
    _write_facts(
        tmp_path, "app.py", "ast",
        imports=[{"source": "lib", "names": ["helper"]}],
    )

    config = _make_config(tmp_path)
    facts_db = FactsDB(config)

    assert _all_importers_ast_extracted("lib.py", facts_db) is True


def test_all_importers_ast_extracted_false_when_llm(tmp_path):
    """Returns False when any importer has LLM-extracted (or no) extraction_method."""
    _write_facts(tmp_path, "lib.py", "ast", exports=[{"name": "helper", "kind": "function"}])
    _write_facts(
        tmp_path, "app.py", "llm",
        imports=[{"source": "lib", "names": ["helper"]}],
    )

    config = _make_config(tmp_path)
    facts_db = FactsDB(config)

    assert _all_importers_ast_extracted("lib.py", facts_db) is False


def test_all_importers_ast_extracted_false_when_none(tmp_path):
    """Returns False when any importer has None extraction_method (legacy)."""
    _write_facts(tmp_path, "lib.py", "ast", exports=[{"name": "helper", "kind": "function"}])
    _write_facts(
        tmp_path, "app.py", None,  # legacy — no extraction_method
        imports=[{"source": "lib", "names": ["helper"]}],
    )

    config = _make_config(tmp_path)
    facts_db = FactsDB(config)

    assert _all_importers_ast_extracted("lib.py", facts_db) is False


def test_all_importers_ast_extracted_no_importers(tmp_path):
    """Returns True when there are no importers (vacuously true)."""
    _write_facts(tmp_path, "lib.py", "ast")

    config = _make_config(tmp_path)
    facts_db = FactsDB(config)

    assert _all_importers_ast_extracted("lib.py", facts_db) is True


def test_group_symbols_by_file():
    all_symbols = {
        "src/a.py": [{"name": "foo", "kind": "function", "line_start": 1}],
        "src\\b.py": [{"name": "bar", "kind": "class", "line_start": 5}],
    }
    grouped = _group_symbols_by_file(all_symbols)
    assert "src/a.py" in grouped
    assert "src/b.py" in grouped


def test_confidence_source_ast_proven():
    """AST-proven findings should have confidence_source='ast_proven'."""
    finding = JunkFinding(
        source_path="lib.py",
        name="dead_func",
        kind="function",
        category="dead_symbol",
        line_start=10,
        line_end=20,
        confidence=1.0,
        reason="No cross-file references found (AST-proven)",
        remediation="Remove function `dead_func`",
        original_purpose="function `dead_func`",
        confidence_source="ast_proven",
    )
    assert finding.confidence_source == "ast_proven"


def test_confidence_source_llm_default():
    """Default confidence_source should be 'llm_inferred'."""
    finding = JunkFinding(
        source_path="lib.py",
        name="maybe_dead",
        kind="function",
        category="dead_symbol",
        line_start=10,
        line_end=20,
        confidence=0.8,
        reason="LLM verified",
        remediation="Remove it",
        original_purpose="function",
    )
    assert finding.confidence_source == "llm_inferred"


def test_mixed_graph_only_full_ast_gets_fast_path(tmp_path):
    """In a mixed AST/LLM graph, only fully-AST files qualify for fast path."""
    # lib.py — AST extracted, but imported by app.py which is LLM-only
    _write_facts(
        tmp_path, "lib.py", "ast",
        exports=[{"name": "helper", "kind": "function"}],
    )
    # app.py — LLM extracted, imports lib
    _write_facts(
        tmp_path, "app.py", "llm",
        imports=[{"source": "lib", "names": ["helper"]}],
    )
    # standalone.py — AST extracted, no importers
    _write_facts(
        tmp_path, "standalone.py", "ast",
        exports=[{"name": "orphan", "kind": "function"}],
    )

    config = _make_config(tmp_path)
    facts_db = FactsDB(config)

    # lib.py is AST but has an LLM importer → not all importers AST
    assert _all_importers_ast_extracted("lib.py", facts_db) is False

    # standalone.py is AST with no importers → qualifies
    assert _all_importers_ast_extracted("standalone.py", facts_db) is True
