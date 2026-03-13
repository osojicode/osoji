"""Tests for orphaned file detection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.junk_orphan import (
    OrphanCandidate,
    OrphanedFilesAnalyzer,
    _build_import_edges,
    _identify_entry_points_heuristic,
    _identify_entry_points_async,
    _identify_relationships_async,
    _load_signatures,
    _verify_orphans_batch_async,
    detect_orphaned_files_async,
    find_orphans,
)
from osoji.llm.types import CompletionResult, ToolCall


# --- Helpers ---

def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _write_signature(temp_dir, source_path, purpose="", topics=None):
    """Helper to write a signature JSON file."""
    sig_path = temp_dir / ".osoji" / "signatures" / (source_path + ".signature.json")
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    sig_path.write_text(json.dumps({
        "path": source_path,
        "purpose": purpose,
        "topics": topics or [],
    }))


# --- TestBuildImportEdges ---

class TestBuildImportEdges:
    def test_finds_cross_file_references(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/a.py", "from b import helper\nhelper()\n")
        _write_source(temp_dir, "src/b.py", "def helper(): pass\n")

        all_symbols = {
            "src/a.py": [{"name": "main", "kind": "function", "line_start": 1}],
            "src/b.py": [{"name": "helper", "kind": "function", "line_start": 1}],
        }
        adjacency = _build_import_edges(all_symbols, config)

        # a.py references helper from b.py, so they should be connected
        assert "src/b.py" in adjacency.get("src/a.py", set())
        assert "src/a.py" in adjacency.get("src/b.py", set())

    def test_no_self_edges(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/a.py", "def foo(): pass\nfoo()\n")

        all_symbols = {
            "src/a.py": [{"name": "foo", "kind": "function", "line_start": 1}],
        }
        adjacency = _build_import_edges(all_symbols, config)

        # a.py should NOT have an edge to itself
        assert "src/a.py" not in adjacency.get("src/a.py", set())

    def test_empty_symbols(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        adjacency = _build_import_edges({}, config)
        assert adjacency == {}

    def test_bidirectional_edges(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/a.py", "import b_func\n")
        _write_source(temp_dir, "src/b.py", "def b_func(): pass\nimport a_func\n")

        all_symbols = {
            "src/a.py": [{"name": "a_func", "kind": "function", "line_start": 1}],
            "src/b.py": [{"name": "b_func", "kind": "function", "line_start": 1}],
        }
        adjacency = _build_import_edges(all_symbols, config)

        assert "src/b.py" in adjacency.get("src/a.py", set())
        assert "src/a.py" in adjacency.get("src/b.py", set())


# --- TestFindOrphans ---

class TestFindOrphans:
    def test_simple_graph(self):
        adjacency = {
            "a.py": {"b.py"},
            "b.py": {"a.py", "c.py"},
            "c.py": {"b.py"},
            "orphan.py": set(),
        }
        entry_points = {"a.py"}
        orphans = find_orphans(adjacency, entry_points)
        assert "orphan.py" in orphans
        assert "a.py" not in orphans
        assert "b.py" not in orphans
        assert "c.py" not in orphans

    def test_all_reachable(self):
        adjacency = {
            "a.py": {"b.py"},
            "b.py": {"a.py"},
        }
        entry_points = {"a.py"}
        orphans = find_orphans(adjacency, entry_points)
        assert orphans == []

    def test_all_orphaned(self):
        adjacency = {
            "a.py": set(),
            "b.py": set(),
        }
        entry_points = set()  # No entry points
        orphans = find_orphans(adjacency, entry_points)
        assert set(orphans) == {"a.py", "b.py"}

    def test_multiple_entry_points(self):
        adjacency = {
            "main.py": {"lib.py"},
            "test.py": {"lib.py"},
            "lib.py": {"main.py", "test.py"},
            "orphan.py": set(),
        }
        entry_points = {"main.py", "test.py"}
        orphans = find_orphans(adjacency, entry_points)
        assert orphans == ["orphan.py"]

    def test_transitive_reachability(self):
        adjacency = {
            "entry.py": {"a.py"},
            "a.py": {"entry.py", "b.py"},
            "b.py": {"a.py", "c.py"},
            "c.py": {"b.py"},
            "orphan.py": set(),
        }
        entry_points = {"entry.py"}
        orphans = find_orphans(adjacency, entry_points)
        assert "orphan.py" in orphans
        assert "c.py" not in orphans  # reachable via entry→a→b→c


# --- TestIdentifyEntryPointsHeuristic ---

class TestIdentifyEntryPointsHeuristic:
    def test_identifies_entry_role(self):
        sigs = [{"path": "src/main.py", "file_role": "entry"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "src/main.py" in result

    def test_identifies_test_role(self):
        sigs = [{"path": "tests/test_foo.py", "file_role": "test"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "tests/test_foo.py" in result

    def test_identifies_init(self):
        sigs = [{"path": "src/__init__.py", "file_role": "utility"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "src/__init__.py" in result

    def test_identifies_conftest(self):
        sigs = [{"path": "tests/conftest.py", "file_role": "config"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "tests/conftest.py" in result

    def test_identifies_test_prefix(self):
        sigs = [{"path": "test_something.py", "file_role": "service"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "test_something.py" in result

    def test_skips_regular_service(self):
        sigs = [{"path": "src/service.py", "file_role": "service"}]
        result = _identify_entry_points_heuristic(sigs)
        assert "src/service.py" not in result


# --- TestHaikuEntryPoints ---

class TestHaikuEntryPoints:
    @pytest.mark.asyncio
    async def test_identifies_entry_points(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="identify_entry_points",
                input={
                    "entry_points": [
                        {"source_path": "src/main.py", "is_entry_point": True, "reason": "CLI entry"},
                        {"source_path": "src/lib.py", "is_entry_point": False, "reason": "Library module"},
                    ],
                },
            )],
            input_tokens=200, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        config = Config(root_path=Path("."), respect_gitignore=False)
        sigs = [
            {"path": "src/main.py", "file_role": "entry", "purpose": "CLI"},
            {"path": "src/lib.py", "file_role": "utility", "purpose": "Helpers"},
        ]
        result = await _identify_entry_points_async(mock_provider, sigs, config)
        assert "src/main.py" in result
        assert "src/lib.py" not in result


# --- TestHaikuRelationships ---

class TestHaikuRelationships:
    @pytest.mark.asyncio
    async def test_identifies_relationships(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="identify_relationships",
                input={
                    "relationships": [
                        {"source_path": "src/plugin.py", "related_to": "src/app.py",
                         "reason": "Plugin loaded by app framework"},
                    ],
                },
            )],
            input_tokens=200, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        config = Config(root_path=Path("."), respect_gitignore=False)
        disconnected = [{"path": "src/plugin.py", "purpose": "Plugin", "topics": ["plugin"]}]
        connected = [{"path": "src/app.py", "purpose": "Main app", "topics": ["app"]}]
        result = await _identify_relationships_async(
            mock_provider, disconnected, connected, config,
        )
        assert ("src/plugin.py", "src/app.py") in result

    @pytest.mark.asyncio
    async def test_empty_disconnected(self):
        mock_provider = AsyncMock()
        config = Config(root_path=Path("."), respect_gitignore=False)
        result = await _identify_relationships_async(
            mock_provider, [], [{"path": "a.py"}], config,
        )
        assert result == []
        mock_provider.complete.assert_not_called()


# --- TestVerifyOrphans ---

class TestVerifyOrphans:
    @pytest.mark.asyncio
    async def test_confirms_orphan(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_orphan_files",
                input={
                    "verdicts": [{
                        "source_path": "src/old.py",
                        "is_orphaned": True, "confidence": 0.9,
                        "reason": "No imports, no dynamic loading",
                        "remediation": "Delete file",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        config = Config(root_path=Path("."), respect_gitignore=False)
        orphans = [OrphanCandidate(
            source_path="src/old.py", purpose="Old utility", topics=["legacy"],
            file_role="utility",
        )]
        results, in_tok, out_tok = await _verify_orphans_batch_async(
            mock_provider, config, orphans, {},
        )
        assert len(results) == 1
        assert results[0].is_orphaned is True
        assert results[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_says_alive(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_orphan_files",
                input={
                    "verdicts": [{
                        "source_path": "src/plugin.py",
                        "is_orphaned": False, "confidence": 0.95,
                        "reason": "Loaded dynamically as pytest plugin",
                        "remediation": "Keep — pytest plugin",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        config = Config(root_path=Path("."), respect_gitignore=False)
        orphans = [OrphanCandidate(
            source_path="src/plugin.py", purpose="Pytest plugin", topics=["testing"],
            file_role="utility",
        )]
        results, _, _ = await _verify_orphans_batch_async(
            mock_provider, config, orphans, {},
        )
        assert len(results) == 1
        assert results[0].is_orphaned is False

    @pytest.mark.asyncio
    async def test_no_tool_calls_raises(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content="No tool response",
            tool_calls=[],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="end_turn",
        )

        config = Config(root_path=Path("."), respect_gitignore=False)
        orphans = [OrphanCandidate(
            source_path="src/old.py", purpose="Old", topics=[],
            file_role="utility",
        )]
        with pytest.raises(RuntimeError, match="did not return verdicts"):
            await _verify_orphans_batch_async(
                mock_provider, config, orphans, {},
            )


# --- TestLoadSignatures ---

class TestLoadSignatures:
    def test_loads_signatures(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_signature(temp_dir, "src/app.py", "Main application", ["app", "server"])
        sigs = _load_signatures(config)
        assert len(sigs) == 1
        assert sigs[0]["path"] == "src/app.py"
        assert sigs[0]["purpose"] == "Main application"

    def test_skips_directory_signatures(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sig_path = temp_dir / ".osoji" / "signatures" / "_directory.signature.json"
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        sig_path.write_text(json.dumps({"path": ".", "purpose": "Root"}))
        sigs = _load_signatures(config)
        assert len(sigs) == 0

    def test_empty_dir(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sigs = _load_signatures(config)
        assert sigs == []


# --- TestOrphanedFilesAnalyzer ---

class TestOrphanedFilesAnalyzer:
    def test_analyzer_properties(self):
        analyzer = OrphanedFilesAnalyzer()
        assert analyzer.name == "orphaned_files"
        assert analyzer.cli_flag == "orphaned-files"
        assert "orphan" in analyzer.description.lower()

    def test_is_junk_analyzer_subclass(self):
        from osoji.junk import JunkAnalyzer
        assert issubclass(OrphanedFilesAnalyzer, JunkAnalyzer)

    @pytest.mark.asyncio
    async def test_skips_without_symbols(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        mock_provider = AsyncMock()
        results, total = await detect_orphaned_files_async(mock_provider, config)
        assert results == []
        assert total == 0
        mock_provider.complete.assert_not_called()
