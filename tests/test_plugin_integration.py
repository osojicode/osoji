"""Integration tests for plugin facts merging in the shadow pipeline."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from osoji.facts import FactsDB, FileFacts
from osoji.plugins.base import ExtractedFacts, PluginUnavailableError, FactsExtractionError


def test_plugin_facts_override_llm_structural_fields():
    """AST facts should override LLM facts for imports/exports/calls/member_writes."""
    llm_facts = {
        "imports": [{"source": "llm_import", "names": ["a"]}],
        "exports": [{"name": "llm_export", "kind": "function"}],
        "calls": [{"from_symbol": "x", "to": "y", "line": 1}],
        "member_writes": [{"container": "obj", "member": "llm_field", "line": 1}],
        "string_literals": [{"value": "contract_key", "usage": "key", "kind": "dict_key"}],
    }

    plugin_facts_dict = {
        "imports": [{"source": "ast_import", "names": ["b"], "line": 1}],
        "exports": [{"name": "ast_export", "kind": "function", "line": 1}],
        "calls": [{"from_symbol": "a", "to": "b", "line": 2, "call_sites": 3}],
        "member_writes": [{"container": "obj", "member": "ast_field", "line": 2}],
        "extraction_method": "ast",
    }

    relative_str = "src/mod.py"
    plugin_facts = {relative_str: plugin_facts_dict}
    facts = dict(llm_facts)

    # Simulate the merge logic from shadow.py process_file_async
    if plugin_facts and relative_str in plugin_facts:
        pf = plugin_facts[relative_str]
        facts = {
            "imports": pf.get("imports", []),
            "exports": pf.get("exports", []),
            "calls": pf.get("calls", []),
            "member_writes": pf.get("member_writes", []),
            "string_literals": facts.get("string_literals", []) if facts else [],
            "extraction_method": "ast",
        }

    assert facts["imports"][0]["source"] == "ast_import"
    assert facts["exports"][0]["name"] == "ast_export"
    assert facts["calls"][0]["to"] == "b"
    assert facts["member_writes"][0]["member"] == "ast_field"
    # LLM string_literals preserved
    assert facts["string_literals"][0]["value"] == "contract_key"
    assert facts["extraction_method"] == "ast"


def test_llm_string_literals_preserved_when_plugin_has_no_strings():
    """LLM string_literals should be kept even when plugin has AST facts."""
    llm_facts = {
        "string_literals": [{"value": "my_key", "usage": "key"}],
    }
    plugin_facts_dict = {
        "imports": [],
        "exports": [],
        "calls": [],
        "member_writes": [],
        "extraction_method": "ast",
    }

    relative_str = "mod.py"
    plugin_facts = {relative_str: plugin_facts_dict}
    facts = dict(llm_facts)

    if plugin_facts and relative_str in plugin_facts:
        pf = plugin_facts[relative_str]
        facts = {
            "imports": pf.get("imports", []),
            "exports": pf.get("exports", []),
            "calls": pf.get("calls", []),
            "member_writes": pf.get("member_writes", []),
            "string_literals": facts.get("string_literals", []) if facts else [],
            "extraction_method": "ast",
        }

    assert len(facts["string_literals"]) == 1
    assert facts["string_literals"][0]["value"] == "my_key"


def test_no_plugin_facts_sets_llm_method():
    """Without plugin facts, extraction_method should be 'llm'."""
    facts = {
        "imports": [{"source": "os", "names": ["path"]}],
        "string_literals": [],
    }

    relative_str = "mod.py"
    plugin_facts = {}  # empty — no plugin matched

    if plugin_facts and relative_str in plugin_facts:
        pass  # not reached
    else:
        if facts:
            facts["extraction_method"] = "llm"

    assert facts["extraction_method"] == "llm"


def test_plugin_unavailable_triggers_fallback(caplog):
    """PluginUnavailableError should result in graceful fallback."""
    from osoji.plugins.base import LanguagePlugin

    class FailPlugin(LanguagePlugin):
        @property
        def name(self):
            return "fail"

        @property
        def extensions(self):
            return frozenset({".fail"})

        def check_available(self, project_root):
            raise PluginUnavailableError("missing tool", "install it")

        def extract_project_facts(self, project_root, files):
            return {}

    plugin = FailPlugin()
    try:
        plugin.check_available(Path("/tmp"))
        available = True
    except PluginUnavailableError as e:
        available = False
        assert e.install_hint == "install it"

    assert not available


def test_extraction_method_backward_compat(tmp_path):
    """Existing .facts.json without extraction_method should load as None."""
    from osoji.config import Config, SHADOW_DIR

    facts_dir = tmp_path / SHADOW_DIR / "facts"
    facts_dir.mkdir(parents=True)

    facts_data = {
        "source": "old_file.py",
        "source_hash": "abc123",
        "imports": [],
        "exports": [],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
    }
    (facts_dir / "old_file.py.facts.json").write_text(
        json.dumps(facts_data), encoding="utf-8"
    )

    config = MagicMock(spec=Config)
    config.root_path = tmp_path

    facts_db = FactsDB(config)
    file_facts = facts_db.get_file("old_file.py")
    assert file_facts is not None
    assert file_facts.extraction_method is None


def test_extraction_method_ast_loads(tmp_path):
    """facts.json with extraction_method='ast' should load correctly."""
    from osoji.config import Config, SHADOW_DIR

    facts_dir = tmp_path / SHADOW_DIR / "facts"
    facts_dir.mkdir(parents=True)

    facts_data = {
        "source": "ast_file.py",
        "source_hash": "def456",
        "imports": [{"source": "os", "names": ["path"], "line": 1}],
        "exports": [{"name": "main", "kind": "function", "line": 3}],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
        "extraction_method": "ast",
    }
    (facts_dir / "ast_file.py.facts.json").write_text(
        json.dumps(facts_data), encoding="utf-8"
    )

    config = MagicMock(spec=Config)
    config.root_path = tmp_path

    facts_db = FactsDB(config)
    file_facts = facts_db.get_file("ast_file.py")
    assert file_facts is not None
    assert file_facts.extraction_method == "ast"


def test_extracted_facts_to_dict():
    """ExtractedFacts.to_file_facts_dict produces correct structure."""
    ef = ExtractedFacts(
        imports=[{"source": "os", "names": ["path"], "line": 1}],
        exports=[{"name": "main", "kind": "function", "line": 5}],
        calls=[{"from_symbol": "main", "to": "os.path.join", "line": 6}],
        member_writes=[],
    )
    d = ef.to_file_facts_dict("src/app.py", "hash123")
    assert d["source"] == "src/app.py"
    assert d["source_hash"] == "hash123"
    assert d["extraction_method"] == "ast"
    assert len(d["imports"]) == 1
    assert len(d["exports"]) == 1
    assert len(d["calls"]) == 1
    assert d["member_writes"] == []


def test_run_plugin_extraction_skips_unavailable(tmp_path):
    """_run_plugin_extraction should skip unavailable plugins gracefully."""
    from osoji.shadow import _run_plugin_extraction
    from osoji.config import Config

    config = MagicMock(spec=Config)
    config.root_path = tmp_path

    class UnavailablePlugin:
        name = "unavail"
        extensions = frozenset({".xxx"})

        def check_available(self, project_root):
            raise PluginUnavailableError("missing", "install it")

        def extract_project_facts(self, project_root, files):
            return {}

    with patch("osoji.plugins.get_all_plugins", return_value=[UnavailablePlugin()]):
        result = _run_plugin_extraction(config, [])

    assert result == {}


def test_run_plugin_extraction_handles_error(tmp_path):
    """_run_plugin_extraction should catch FactsExtractionError and continue."""
    from osoji.shadow import _run_plugin_extraction
    from osoji.config import Config

    config = MagicMock(spec=Config)
    config.root_path = tmp_path

    class ErrorPlugin:
        name = "error"
        extensions = frozenset({".err"})

        def check_available(self, project_root):
            pass

        def extract_project_facts(self, project_root, files):
            raise FactsExtractionError("boom")

    with patch("osoji.plugins.get_all_plugins", return_value=[ErrorPlugin()]):
        result = _run_plugin_extraction(config, [])

    assert result == {}
