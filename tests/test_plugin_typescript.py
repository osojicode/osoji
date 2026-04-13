"""Tests for TypeScript plugin — all subprocess calls mocked, no real Node.js required."""

from unittest.mock import patch, MagicMock
from pathlib import Path

import json
import pytest

from osoji.plugins.base import PluginUnavailableError, FactsExtractionError
from osoji.plugins.typescript_plugin import (
    TypeScriptPlugin,
    _find_all_tsconfigs,
    _detect_workspace_packages,
)


@pytest.fixture
def plugin():
    return TypeScriptPlugin()


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


def test_check_available_no_node(plugin, tmp_path):
    with patch("osoji.plugins.typescript_plugin.shutil.which", return_value=None):
        with pytest.raises(PluginUnavailableError, match="Node.js not found"):
            plugin.check_available(tmp_path)


def test_check_available_no_ts_morph(plugin, tmp_path):
    """When ts-morph check fails and npm install also fails, raise."""
    failed = MagicMock(returncode=1)
    with patch("osoji.plugins.typescript_plugin.shutil.which", return_value="/usr/bin/node"):
        with patch(
            "osoji.plugins.typescript_plugin.subprocess.run",
            return_value=failed,
        ):
            with pytest.raises(PluginUnavailableError, match="Failed to install"):
                plugin.check_available(tmp_path)


def test_check_available_ts_morph_not_found(plugin, tmp_path):
    """When ts-morph check fails and npm not available, raise."""
    failed = MagicMock(returncode=1)
    with patch("osoji.plugins.typescript_plugin.shutil.which", side_effect=lambda x: "/usr/bin/node" if x == "node" else None):
        with patch(
            "osoji.plugins.typescript_plugin.subprocess.run",
            return_value=failed,
        ):
            with pytest.raises(PluginUnavailableError, match="npm not available"):
                plugin.check_available(tmp_path)


def test_no_tsconfig_raises(plugin, tmp_path):
    """extract_project_facts raises FactsExtractionError when no tsconfig."""
    with patch.object(plugin, "check_available"):
        with pytest.raises(FactsExtractionError, match="No tsconfig.json"):
            plugin.extract_project_facts(tmp_path, [tmp_path / "foo.ts"])


def test_extract_calls_node(plugin, tmp_path):
    """Successful extraction parses JSON from node subprocess."""

    # Create tsconfig so _find_all_tsconfigs succeeds
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


# ---------------------------------------------------------------------------
# New tests: class method exports
# ---------------------------------------------------------------------------


def test_class_method_exports(plugin, tmp_path):
    """Mock returns ClassName.methodName exports — plugin surfaces them."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "service.ts"
    ts_file.write_text("export class UserService { findAll() {} }", encoding="utf-8")

    mock_output = json.dumps({
        "service.ts": {
            "imports": [],
            "exports": [
                {"name": "UserService", "kind": "class", "line": 1,
                 "decorators": [], "exclude_from_dead_analysis": False},
                {"name": "UserService.findAll", "kind": "function", "line": 1,
                 "decorators": [], "exclude_from_dead_analysis": False},
            ],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    export_names = [e["name"] for e in result["service.ts"].exports]
    assert "UserService" in export_names
    assert "UserService.findAll" in export_names


# ---------------------------------------------------------------------------
# New tests: parameter extraction
# ---------------------------------------------------------------------------


def test_parameter_extraction(plugin, tmp_path):
    """Exports include parameters array for functions."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "config.ts"
    ts_file.write_text("export function load(path: string) {}", encoding="utf-8")

    mock_output = json.dumps({
        "config.ts": {
            "imports": [],
            "exports": [
                {
                    "name": "load",
                    "kind": "function",
                    "line": 1,
                    "decorators": [],
                    "exclude_from_dead_analysis": False,
                    "parameters": [
                        {"name": "path", "optional": False, "type": "string"},
                    ],
                },
            ],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    exp = result["config.ts"].exports[0]
    assert "parameters" in exp
    assert exp["parameters"][0]["name"] == "path"
    assert exp["parameters"][0]["type"] == "string"
    assert exp["parameters"][0]["optional"] is False


# ---------------------------------------------------------------------------
# New tests: framework decorator detection
# ---------------------------------------------------------------------------


def test_framework_decorator_detection(plugin, tmp_path):
    """Decorators set exclude_from_dead_analysis: true."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "controller.ts"
    ts_file.write_text("@Controller() export class AppController {}", encoding="utf-8")

    mock_output = json.dumps({
        "controller.ts": {
            "imports": [],
            "exports": [
                {
                    "name": "AppController",
                    "kind": "class",
                    "line": 1,
                    "decorators": ["Controller"],
                    "exclude_from_dead_analysis": True,
                },
            ],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    exp = result["controller.ts"].exports[0]
    assert exp["exclude_from_dead_analysis"] is True
    assert "Controller" in exp["decorators"]


# ---------------------------------------------------------------------------
# New tests: cross-file call sites
# ---------------------------------------------------------------------------


def test_cross_file_call_sites(plugin, tmp_path):
    """call_sites reflects project-wide count from extract.js output."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file_a = tmp_path / "a.ts"
    ts_file_b = tmp_path / "b.ts"
    ts_file_a.write_text("export function greet() {}", encoding="utf-8")
    ts_file_b.write_text("import {greet} from './a'; greet();", encoding="utf-8")

    mock_output = json.dumps({
        "a.ts": {
            "imports": [],
            "exports": [{"name": "greet", "kind": "function", "line": 1,
                          "decorators": [], "exclude_from_dead_analysis": False}],
            "calls": [],
            "member_writes": [],
        },
        "b.ts": {
            "imports": [{"source": "./a", "names": ["greet"], "line": 1,
                          "is_reexport": False, "resolved_path": "a.ts"}],
            "exports": [],
            "calls": [{"from_symbol": "<module>", "to": "greet", "line": 1, "call_sites": 1}],
            "member_writes": [],
        },
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file_a, ts_file_b])

    assert result["b.ts"].calls[0]["call_sites"] == 1


# ---------------------------------------------------------------------------
# New tests: import resolved_path
# ---------------------------------------------------------------------------


def test_import_resolved_path(plugin, tmp_path):
    """Imports include resolved_path when target is a project file."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "main.ts"
    ts_file.write_text("import { helper } from './utils';", encoding="utf-8")

    mock_output = json.dumps({
        "main.ts": {
            "imports": [
                {
                    "source": "./utils",
                    "names": ["helper"],
                    "line": 1,
                    "is_reexport": False,
                    "resolved_path": "utils.ts",
                },
            ],
            "exports": [],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    imp = result["main.ts"].imports[0]
    assert imp["resolved_path"] == "utils.ts"


# ---------------------------------------------------------------------------
# New tests: interface implementation
# ---------------------------------------------------------------------------


def test_interface_implementation(plugin, tmp_path):
    """Class exports include implements list."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "repo.ts"
    ts_file.write_text("export class UserRepo implements Repository {}", encoding="utf-8")

    mock_output = json.dumps({
        "repo.ts": {
            "imports": [],
            "exports": [
                {
                    "name": "UserRepo",
                    "kind": "class",
                    "line": 1,
                    "decorators": [],
                    "exclude_from_dead_analysis": False,
                    "implements": ["Repository"],
                },
            ],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    exp = result["repo.ts"].exports[0]
    assert exp["implements"] == ["Repository"]


# ---------------------------------------------------------------------------
# New tests: star re-export
# ---------------------------------------------------------------------------


def test_star_reexport(plugin, tmp_path):
    """export * from creates reexport import record with names=['*']."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "index.ts"
    ts_file.write_text("export * from './module';", encoding="utf-8")

    mock_output = json.dumps({
        "index.ts": {
            "imports": [
                {
                    "source": "./module",
                    "names": ["*"],
                    "line": 1,
                    "is_reexport": True,
                    "resolved_path": "module.ts",
                },
            ],
            "exports": [],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    imp = result["index.ts"].imports[0]
    assert imp["names"] == ["*"]
    assert imp["is_reexport"] is True


# ---------------------------------------------------------------------------
# New tests: constructor calls
# ---------------------------------------------------------------------------


def test_constructor_calls(plugin, tmp_path):
    """new X() appears in calls."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("const x = new Map();", encoding="utf-8")

    mock_output = json.dumps({
        "app.ts": {
            "imports": [],
            "exports": [],
            "calls": [
                {"from_symbol": "<module>", "to": "Map", "line": 1, "call_sites": 1},
            ],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    assert any(c["to"] == "Map" for c in result["app.ts"].calls)


# ---------------------------------------------------------------------------
# New tests: scope-qualified from_symbol
# ---------------------------------------------------------------------------


def test_scope_qualified_from_symbol(plugin, tmp_path):
    """Calls inside class methods have ClassName.methodName in from_symbol."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "svc.ts"
    ts_file.write_text("export class Svc { run() { doWork(); } }", encoding="utf-8")

    mock_output = json.dumps({
        "svc.ts": {
            "imports": [],
            "exports": [
                {"name": "Svc", "kind": "class", "line": 1,
                 "decorators": [], "exclude_from_dead_analysis": False},
                {"name": "Svc.run", "kind": "function", "line": 1,
                 "decorators": [], "exclude_from_dead_analysis": False},
            ],
            "calls": [
                {"from_symbol": "Svc.run", "to": "doWork", "line": 1, "call_sites": 1},
            ],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc):
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    call = result["svc.ts"].calls[0]
    assert call["from_symbol"] == "Svc.run"


# ---------------------------------------------------------------------------
# New tests: monorepo tsconfig discovery
# ---------------------------------------------------------------------------


def test_monorepo_tsconfig_discovery(tmp_path):
    """_find_all_tsconfigs finds multiple tsconfigs across the tree."""
    # Root tsconfig
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    # Package tsconfigs
    pkg_a = tmp_path / "packages" / "a"
    pkg_a.mkdir(parents=True)
    (pkg_a / "tsconfig.json").write_text("{}", encoding="utf-8")

    pkg_b = tmp_path / "packages" / "b"
    pkg_b.mkdir(parents=True)
    (pkg_b / "tsconfig.json").write_text("{}", encoding="utf-8")

    # Excluded: node_modules
    nm = tmp_path / "node_modules" / "foo"
    nm.mkdir(parents=True)
    (nm / "tsconfig.json").write_text("{}", encoding="utf-8")

    found = _find_all_tsconfigs(tmp_path)
    found_strs = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in found}

    assert "tsconfig.json" in found_strs
    assert "packages/a/tsconfig.json" in found_strs
    assert "packages/b/tsconfig.json" in found_strs
    # node_modules should be excluded
    assert not any("node_modules" in s for s in found_strs)


# ---------------------------------------------------------------------------
# New tests: workspace package detection — pnpm
# ---------------------------------------------------------------------------


def test_workspace_package_detection_pnpm(tmp_path):
    """Reads pnpm-workspace.yaml and detects package names."""
    # pnpm-workspace.yaml
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'packages/*'\n", encoding="utf-8"
    )

    # Package dirs
    pkg = tmp_path / "packages" / "core"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@myorg/core"}), encoding="utf-8"
    )

    result = _detect_workspace_packages(tmp_path)
    assert "@myorg/core" in result
    # Value should be a relative path string
    assert "packages/core" in result["@myorg/core"]


# ---------------------------------------------------------------------------
# New tests: workspace package detection — npm
# ---------------------------------------------------------------------------


def test_workspace_package_detection_npm(tmp_path):
    """Reads package.json workspaces field and detects package names."""
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["packages/*"]}), encoding="utf-8"
    )

    pkg = tmp_path / "packages" / "ui"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@myorg/ui"}), encoding="utf-8"
    )

    result = _detect_workspace_packages(tmp_path)
    assert "@myorg/ui" in result


# ---------------------------------------------------------------------------
# New tests: backward compat array input
# ---------------------------------------------------------------------------


def test_object_format_input(plugin, tmp_path):
    """Plugin sends new object format with files key."""
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    ts_file = tmp_path / "lib.ts"
    ts_file.write_text("export const a = 1;", encoding="utf-8")

    mock_output = json.dumps({
        "lib.ts": {
            "imports": [],
            "exports": [{"name": "a", "kind": "variable", "line": 1,
                          "decorators": [], "exclude_from_dead_analysis": False}],
            "calls": [],
            "member_writes": [],
        }
    })
    mock_proc = MagicMock(returncode=0, stdout=mock_output, stderr="")

    with patch.object(plugin, "check_available"):
        with patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc) as mock_run:
            result = plugin.extract_project_facts(tmp_path, [ts_file])

    # Verify the new object format is sent
    call_args = mock_run.call_args
    stdin_data = json.loads(call_args.kwargs.get("input", call_args[1].get("input", "")))
    assert "files" in stdin_data
    assert "workspacePackages" in stdin_data
    assert "lib.ts" in stdin_data["files"]

    assert "lib.ts" in result
