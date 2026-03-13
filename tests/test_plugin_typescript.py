"""Tests for TypeScript plugin — all subprocess calls mocked, no real Node.js required."""

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from osoji.plugins.base import PluginUnavailableError, FactsExtractionError
from osoji.plugins.typescript_plugin import TypeScriptPlugin


@pytest.fixture
def plugin():
    return TypeScriptPlugin()


def test_check_available_no_node(plugin, tmp_path):
    with patch("osoji.plugins.typescript_plugin.shutil.which", return_value=None):
        with pytest.raises(PluginUnavailableError, match="Node.js not found"):
            plugin.check_available(tmp_path)


def test_check_available_no_ts_morph(plugin, tmp_path):
    import subprocess as sp
    with patch("osoji.plugins.typescript_plugin.shutil.which", return_value="/usr/bin/node"):
        with patch(
            "osoji.plugins.typescript_plugin.subprocess.run",
            side_effect=sp.CalledProcessError(1, "node"),
        ):
            with pytest.raises(PluginUnavailableError, match="ts-morph not found"):
                plugin.check_available(tmp_path)


def test_check_available_ts_morph_not_found(plugin, tmp_path):
    """subprocess.CalledProcessError when require('ts-morph') fails."""
    import subprocess as sp

    with patch("osoji.plugins.typescript_plugin.shutil.which", return_value="/usr/bin/node"):
        with patch(
            "osoji.plugins.typescript_plugin.subprocess.run",
            side_effect=sp.CalledProcessError(1, "node"),
        ):
            with pytest.raises(PluginUnavailableError):
                plugin.check_available(tmp_path)


def test_no_tsconfig_raises(plugin, tmp_path):
    """extract_project_facts raises FactsExtractionError when no tsconfig."""
    with patch.object(plugin, "check_available"):
        with pytest.raises(FactsExtractionError, match="No tsconfig.json"):
            plugin.extract_project_facts(tmp_path, [tmp_path / "foo.ts"])


def test_extract_calls_node(plugin, tmp_path):
    """Successful extraction parses JSON from node subprocess."""
    import json
    import subprocess as sp

    # Create tsconfig so _find_tsconfig succeeds
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("export const x = 1;", encoding="utf-8")

    mock_output = json.dumps({
        "app.ts": {
            "imports": [{"source": "./lib", "names": ["foo"], "line": 1, "is_reexport": False}],
            "exports": [{"name": "x", "kind": "variable", "line": 1, "decorators": [], "exclude_from_dead_analysis": False}],
            "calls": [],
            "member_writes": [],
        }
    })

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = mock_output
    mock_proc.stderr = ""

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    assert "app.ts" in result
    assert len(result["app.ts"].exports) == 1
    assert result["app.ts"].exports[0]["name"] == "x"


def test_extract_node_failure(plugin, tmp_path):
    """Node subprocess failure raises FactsExtractionError."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "SyntaxError: Unexpected"

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            with pytest.raises(FactsExtractionError, match="exit 1"):
                plugin.extract_project_facts(tmp_path, [ts_file])


def test_extract_timeout(plugin, tmp_path):
    """Node subprocess timeout raises FactsExtractionError."""
    import subprocess as sp

    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("", encoding="utf-8")

    with patch.object(plugin, "check_available"):
        with patch(
            "osoji.plugins.typescript_plugin.subprocess.run",
            side_effect=sp.TimeoutExpired("node", 120),
        ):
            with pytest.raises(FactsExtractionError, match="timed out"):
                plugin.extract_project_facts(tmp_path, [ts_file])


def test_no_ts_files_returns_empty(plugin, tmp_path):
    """If no .ts/.tsx/.mts files in list, return empty dict."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    py_file = tmp_path / "main.py"
    py_file.write_text("x = 1", encoding="utf-8")

    with patch.object(plugin, "check_available"):
        result = plugin.extract_project_facts(tmp_path, [py_file])

    assert result == {}


def test_plugin_properties(plugin):
    assert plugin.name == "typescript"
    assert ".ts" in plugin.extensions
    assert ".tsx" in plugin.extensions
    assert ".mts" in plugin.extensions


def test_find_tsconfig_walks_up(plugin, tmp_path):
    """_find_tsconfig should find tsconfig.json in parent directories."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    subdir = tmp_path / "src" / "components"
    subdir.mkdir(parents=True)

    result = TypeScriptPlugin._find_tsconfig(subdir)
    assert result is not None
    assert result.name == "tsconfig.json"


def test_find_tsconfig_none_when_missing(plugin, tmp_path):
    """_find_tsconfig returns None when no tsconfig exists."""
    result = TypeScriptPlugin._find_tsconfig(tmp_path)
    assert result is None
