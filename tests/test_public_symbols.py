"""Tests for symbols extraction, persistence, and loading."""

import json
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.symbols import load_all_symbols


class TestSymbolsPathFor:
    """Config.symbols_path_for() returns the correct sidecar path."""

    def test_basic_path(self, temp_dir):
        config = Config(root_path=temp_dir)
        src = temp_dir / "src" / "main.py"
        expected = temp_dir / ".docstar" / "symbols" / "src" / "main.py.symbols.json"
        assert config.symbols_path_for(src) == expected

    def test_nested_path(self, temp_dir):
        config = Config(root_path=temp_dir)
        src = temp_dir / "a" / "b" / "c.py"
        result = config.symbols_path_for(src)
        assert result.name == "c.py.symbols.json"
        assert "symbols" in result.parts


class TestExtractSymbols:
    """Verify symbols are correctly extracted from a mock tool call response."""

    def test_extract_from_tool_input(self):
        """Simulate what generate_file_shadow_doc_async does with the tool call input."""
        tool_input = {
            "content": "Shadow doc body text",
            "findings": [],
            "symbols": [
                {"name": "Config", "kind": "class", "line_start": 10, "line_end": 50, "visibility": "public"},
                {"name": "DEFAULT_MODEL", "kind": "constant", "line_start": 5, "visibility": "public"},
                {"name": "_helper", "kind": "function", "line_start": 60, "line_end": 80, "visibility": "internal"},
            ],
        }
        symbols = tool_input.get("symbols") or tool_input.get("public_symbols", [])
        assert len(symbols) == 3
        assert symbols[0]["name"] == "Config"
        assert symbols[0]["kind"] == "class"
        assert symbols[0]["visibility"] == "public"
        assert symbols[1]["name"] == "DEFAULT_MODEL"
        assert symbols[1]["kind"] == "constant"
        assert symbols[2]["name"] == "_helper"
        assert symbols[2]["visibility"] == "internal"

    def test_missing_symbols_defaults_empty(self):
        """When LLM omits symbols, default to empty list."""
        tool_input = {
            "content": "Shadow doc body text",
            "findings": [],
        }
        symbols = tool_input.get("symbols") or tool_input.get("public_symbols", [])
        assert symbols == []

    def test_backward_compat_public_symbols_key(self):
        """Old LLM responses with public_symbols key still work."""
        tool_input = {
            "content": "Shadow doc body text",
            "findings": [],
            "public_symbols": [
                {"name": "Config", "kind": "class", "line_start": 10},
            ],
        }
        symbols = tool_input.get("symbols") or tool_input.get("public_symbols", [])
        assert len(symbols) == 1
        assert symbols[0]["name"] == "Config"


class TestLoadAllSymbols:
    """Verify load_all_symbols reads and aggregates symbol files."""

    def test_loads_single_file(self, temp_dir):
        config = Config(root_path=temp_dir)
        symbols_dir = temp_dir / ".docstar" / "symbols" / "src"
        symbols_dir.mkdir(parents=True)

        data = {
            "source": "src/main.py",
            "source_hash": "abc123",
            "generated": "2025-01-01T00:00:00Z",
            "symbols": [
                {"name": "main", "kind": "function", "line_start": 1, "line_end": 10},
            ],
        }
        (symbols_dir / "main.py.symbols.json").write_text(json.dumps(data))

        result = load_all_symbols(config)
        assert "src/main.py" in result
        assert len(result["src/main.py"]) == 1
        assert result["src/main.py"][0]["name"] == "main"

    def test_loads_multiple_files(self, temp_dir):
        config = Config(root_path=temp_dir)
        symbols_dir = temp_dir / ".docstar" / "symbols"
        symbols_dir.mkdir(parents=True)

        for name, source in [("a.py", "a.py"), ("b.py", "b.py")]:
            data = {
                "source": source,
                "source_hash": "hash",
                "generated": "2025-01-01T00:00:00Z",
                "symbols": [
                    {"name": name.replace(".py", ""), "kind": "function", "line_start": 1},
                ],
            }
            (symbols_dir / f"{name}.symbols.json").write_text(json.dumps(data))

        result = load_all_symbols(config)
        assert len(result) == 2
        assert "a.py" in result
        assert "b.py" in result

    def test_empty_when_no_dir(self, temp_dir):
        config = Config(root_path=temp_dir)
        result = load_all_symbols(config)
        assert result == {}

    def test_skips_empty_symbols(self, temp_dir):
        config = Config(root_path=temp_dir)
        symbols_dir = temp_dir / ".docstar" / "symbols"
        symbols_dir.mkdir(parents=True)

        data = {
            "source": "empty.py",
            "source_hash": "hash",
            "generated": "2025-01-01T00:00:00Z",
            "symbols": [],
        }
        (symbols_dir / "empty.py.symbols.json").write_text(json.dumps(data))

        result = load_all_symbols(config)
        assert result == {}

    def test_skips_malformed_json(self, temp_dir):
        config = Config(root_path=temp_dir)
        symbols_dir = temp_dir / ".docstar" / "symbols"
        symbols_dir.mkdir(parents=True)

        (symbols_dir / "bad.py.symbols.json").write_text("not json{{{")

        result = load_all_symbols(config)
        assert result == {}
