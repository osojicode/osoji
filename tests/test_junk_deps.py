"""Tests for dead dependency detection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.junk import JunkAnalysisResult
from osoji.junk_deps import (
    DeadDepsAnalyzer,
    DependencyCandidate,
    DepVerification,
    _BUILD_TOOLS_CACHE,
    _IMPORT_NAME_CACHE,
    _classify_deps_batch_async,
    _filter_zero_import,
    _parse_package_json,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    _resolve_import_names_batch_async,
    _resolve_import_names_heuristic,
    _verify_batch_async,
    detect_dead_deps_async,
    discover_manifests,
    parse_manifest,
    scan_imports,
)
from osoji.llm.types import CompletionResult, ToolCall


# --- Helpers ---

def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


# --- TestDiscoverManifests ---

class TestDiscoverManifests:
    def test_finds_pyproject_toml(self, temp_dir):
        _write_source(temp_dir, "pyproject.toml", "[project]\nname = 'foo'\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        manifests = discover_manifests(config)
        paths = [m[0] for m in manifests]
        assert "pyproject.toml" in paths

    def test_finds_requirements_txt(self, temp_dir):
        _write_source(temp_dir, "requirements.txt", "requests>=2.0\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        manifests = discover_manifests(config)
        paths = [m[0] for m in manifests]
        assert "requirements.txt" in paths

    def test_finds_requirements_dev_txt(self, temp_dir):
        _write_source(temp_dir, "requirements-dev.txt", "pytest\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        manifests = discover_manifests(config)
        paths = [m[0] for m in manifests]
        assert "requirements-dev.txt" in paths

    def test_finds_package_json(self, temp_dir):
        _write_source(temp_dir, "package.json", '{"dependencies": {}}\n')
        config = Config(root_path=temp_dir, respect_gitignore=False)
        manifests = discover_manifests(config)
        paths = [m[0] for m in manifests]
        assert "package.json" in paths
        ecosystems = {m[0]: m[1] for m in manifests}
        assert ecosystems["package.json"] == "node"

    def test_ignores_missing_files(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        manifests = discover_manifests(config)
        assert manifests == []


# --- TestParseRequirements ---

class TestParseRequirements:
    def test_parses_simple_packages(self):
        content = "requests\nflask\n"
        result = _parse_requirements_txt(content, "requirements.txt")
        names = [c.package_name for c in result]
        assert "requests" in names
        assert "flask" in names

    def test_parses_versions_and_extras(self):
        content = "requests>=2.0,<3.0\nflask[async]>=2.0\n"
        result = _parse_requirements_txt(content, "requirements.txt")
        names = [c.package_name for c in result]
        assert "requests" in names
        assert "flask" in names

    def test_skips_comments_and_blanks(self):
        content = "# comment\n\nrequests\n  # another\n"
        result = _parse_requirements_txt(content, "requirements.txt")
        names = [c.package_name for c in result]
        assert names == ["requests"]

    def test_skips_directives(self):
        content = "-r other.txt\n-c constraints.txt\n-e .\n-f http://example.com\nrequests\n"
        result = _parse_requirements_txt(content, "requirements.txt")
        names = [c.package_name for c in result]
        assert names == ["requests"]

    def test_line_numbers(self):
        content = "requests\nflask\n"
        result = _parse_requirements_txt(content, "requirements.txt")
        assert result[0].line_number == 1
        assert result[1].line_number == 2


# --- TestParsePyproject ---

class TestParsePyproject:
    def test_project_dependencies(self):
        content = """
[project]
dependencies = ["requests>=2.0", "click"]
"""
        result = _parse_pyproject_toml(content, "pyproject.toml")
        names = [c.package_name for c in result]
        assert "requests" in names
        assert "click" in names

    def test_optional_dependencies(self):
        content = """
[project.optional-dependencies]
dev = ["pytest", "black"]
"""
        result = _parse_pyproject_toml(content, "pyproject.toml")
        names = [c.package_name for c in result]
        assert "pytest" in names
        assert "black" in names
        assert all(c.is_dev for c in result)

    def test_poetry_dependencies(self):
        content = """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.28"
"""
        result = _parse_pyproject_toml(content, "pyproject.toml")
        names = [c.package_name for c in result]
        assert "requests" in names
        # python should be excluded
        assert "python" not in names

    def test_poetry_group_dependencies(self):
        content = """
[tool.poetry.group.dev.dependencies]
pytest = "^7.0"
"""
        result = _parse_pyproject_toml(content, "pyproject.toml")
        names = [c.package_name for c in result]
        assert "pytest" in names
        assert result[0].is_dev is True

    def test_build_system_requires(self):
        content = """
[build-system]
requires = ["setuptools>=68.0", "wheel"]
"""
        result = _parse_pyproject_toml(content, "pyproject.toml")
        names = [c.package_name for c in result]
        assert "setuptools" in names
        assert "wheel" in names


# --- TestParsePackageJson ---

class TestParsePackageJson:
    def test_dependencies(self):
        content = json.dumps({
            "dependencies": {"express": "^4.0", "lodash": "^4.17"},
        })
        result = _parse_package_json(content, "package.json")
        names = [c.package_name for c in result]
        assert "express" in names
        assert "lodash" in names
        assert not any(c.is_dev for c in result)

    def test_dev_dependencies(self):
        content = json.dumps({
            "devDependencies": {"jest": "^29.0", "typescript": "^5.0"},
        })
        result = _parse_package_json(content, "package.json")
        names = [c.package_name for c in result]
        assert "jest" in names
        assert all(c.is_dev for c in result)

    def test_peer_dependencies(self):
        content = json.dumps({
            "peerDependencies": {"react": "^18.0"},
        })
        result = _parse_package_json(content, "package.json")
        names = [c.package_name for c in result]
        assert "react" in names

    def test_scoped_packages(self):
        content = json.dumps({
            "dependencies": {"@types/node": "^20.0", "@scope/pkg": "^1.0"},
        })
        result = _parse_package_json(content, "package.json")
        names = [c.package_name for c in result]
        assert "@types/node" in names
        assert "@scope/pkg" in names


# --- TestResolveImportNames ---

class TestResolveImportNames:
    def test_known_mismatch_pillow(self):
        result = _resolve_import_names_heuristic("Pillow", "python")
        assert "PIL" in result

    def test_known_mismatch_scikit_learn(self):
        result = _resolve_import_names_heuristic("scikit-learn", "python")
        assert "sklearn" in result

    def test_known_mismatch_pyyaml(self):
        result = _resolve_import_names_heuristic("PyYAML", "python")
        assert "yaml" in result

    def test_heuristic_fallback(self):
        result = _resolve_import_names_heuristic("my-package", "python")
        assert "my_package" in result

    def test_node_exact_name(self):
        result = _resolve_import_names_heuristic("express", "node")
        assert result == ["express"]

    def test_node_scoped_package(self):
        result = _resolve_import_names_heuristic("@scope/name", "node")
        assert result == ["@scope/name"]

    def test_rust_hyphens_to_underscores(self):
        result = _resolve_import_names_heuristic("serde-json", "rust")
        assert result == ["serde_json"]

    def test_go_last_segment(self):
        result = _resolve_import_names_heuristic("github.com/foo/bar", "go")
        assert result == ["bar"]


# --- TestScanImports ---

class TestScanImports:
    def test_finds_import(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "import requests\nrequests.get('http://example.com')\n")
        _write_source(temp_dir, "requirements.txt", "requests\n")

        candidates = [DependencyCandidate(
            manifest_path="requirements.txt", package_name="requests",
            import_names=["requests"], ecosystem="python", line_number=1,
        )]
        scan_imports(config, candidates)
        assert candidates[0].import_hits > 0
        assert "src/app.py" in candidates[0].hit_files

    def test_word_boundary(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "# not_requests, just a comment\n")
        _write_source(temp_dir, "requirements.txt", "requests\n")

        candidates = [DependencyCandidate(
            manifest_path="requirements.txt", package_name="requests",
            import_names=["requests"], ecosystem="python", line_number=1,
        )]
        scan_imports(config, candidates)
        # "not_requests" should NOT match because of word boundary
        # But "requests" is a substring at word boundary within "not_requests"
        # Actually \b between _ and r: _r has no boundary. So this should NOT match.
        assert candidates[0].import_hits == 0

    def test_multiple_import_names(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "from PIL import Image\n")
        _write_source(temp_dir, "requirements.txt", "Pillow\n")

        candidates = [DependencyCandidate(
            manifest_path="requirements.txt", package_name="Pillow",
            import_names=["PIL"], ecosystem="python", line_number=1,
        )]
        scan_imports(config, candidates)
        assert candidates[0].import_hits > 0


# --- TestFilterZeroImport ---

class TestFilterZeroImport:
    """_filter_zero_import only checks import_hits.
    Build tool / @types filtering moved to _BUILD_TOOLS_CACHE pre-filter + Haiku classification.
    """

    def test_keeps_zero_import(self):
        candidates = [
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="black",
                import_names=["black"], ecosystem="python", line_number=1,
                import_hits=0,
            ),
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="some-unused-lib",
                import_names=["some_unused_lib"], ecosystem="python", line_number=2,
                import_hits=0,
            ),
        ]
        filtered = _filter_zero_import(candidates)
        # Both have zero imports, so both pass the zero-import filter
        assert len(filtered) == 2

    def test_keeps_genuine_zero_import(self):
        candidates = [
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="unused-pkg",
                import_names=["unused_pkg"], ecosystem="python", line_number=1,
                import_hits=0,
            ),
        ]
        filtered = _filter_zero_import(candidates)
        assert len(filtered) == 1

    def test_excludes_imported_packages(self):
        candidates = [
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="requests",
                import_names=["requests"], ecosystem="python", line_number=1,
                import_hits=3, hit_files=["a.py", "b.py", "c.py"],
            ),
        ]
        filtered = _filter_zero_import(candidates)
        assert len(filtered) == 0


# --- TestBuildToolsCache ---

class TestBuildToolsCache:
    """_BUILD_TOOLS_CACHE is the merged set of known build tools (pre-filter before Haiku)."""

    def test_python_build_tools_in_cache(self):
        assert "black" in _BUILD_TOOLS_CACHE
        assert "ruff" in _BUILD_TOOLS_CACHE
        assert "pytest" in _BUILD_TOOLS_CACHE
        assert "mypy" in _BUILD_TOOLS_CACHE

    def test_node_build_tools_in_cache(self):
        assert "typescript" in _BUILD_TOOLS_CACHE
        assert "eslint" in _BUILD_TOOLS_CACHE
        assert "webpack" in _BUILD_TOOLS_CACHE

    def test_import_name_cache_has_known_mismatches(self):
        assert "pillow" in _IMPORT_NAME_CACHE
        assert _IMPORT_NAME_CACHE["pillow"] == ["PIL"]
        assert "scikit-learn" in _IMPORT_NAME_CACHE


# --- TestHaikuImportResolution ---

class TestHaikuImportResolution:
    @pytest.mark.asyncio
    async def test_batch_resolve_returns_mappings(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="resolve_import_names",
                input={
                    "resolutions": [
                        {"package_name": "my-pkg", "import_names": ["my_pkg"]},
                        {"package_name": "another", "import_names": ["another"]},
                    ],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )

        resolved, in_tok, out_tok = await _resolve_import_names_batch_async(
            mock_provider, [("my-pkg", "python"), ("another", "python")],
        )
        assert resolved["my-pkg"] == ["my_pkg"]
        assert resolved["another"] == ["another"]
        assert in_tok == 100

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        mock_provider = AsyncMock()
        resolved, in_tok, out_tok = await _resolve_import_names_batch_async(
            mock_provider, [],
        )
        assert resolved == {}
        assert in_tok == 0
        mock_provider.complete.assert_not_called()


# --- TestHaikuDepClassification ---

class TestHaikuDepClassification:
    @pytest.mark.asyncio
    async def test_classify_filters_build_tools(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="classify_deps",
                input={
                    "classifications": [
                        {"package_name": "some-linter", "classification": "build_tool", "brief_reason": "Linting tool"},
                        {"package_name": "unused-lib", "classification": "genuine_candidate", "brief_reason": "Not a known tool"},
                    ],
                },
            )],
            input_tokens=150, output_tokens=60,
            model="test", stop_reason="tool_use",
        )

        candidates = [
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="some-linter",
                import_names=["some_linter"], ecosystem="python", line_number=1,
            ),
            DependencyCandidate(
                manifest_path="requirements.txt", package_name="unused-lib",
                import_names=["unused_lib"], ecosystem="python", line_number=2,
            ),
        ]
        genuine, class_map, in_tok, out_tok = await _classify_deps_batch_async(
            mock_provider, candidates, "some-linter\nunused-lib\n",
        )
        assert len(genuine) == 1
        assert genuine[0].package_name == "unused-lib"
        assert class_map["some-linter"] == "build_tool"
        assert class_map["unused-lib"] == "genuine_candidate"

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        mock_provider = AsyncMock()
        genuine, class_map, in_tok, out_tok = await _classify_deps_batch_async(
            mock_provider, [], "",
        )
        assert genuine == []
        assert class_map == {}
        mock_provider.complete.assert_not_called()


# --- TestVerifyBatch ---

class TestVerifyBatch:
    @pytest.fixture
    def config(self, temp_dir):
        return Config(root_path=temp_dir, respect_gitignore=False)

    @pytest.mark.asyncio
    async def test_llm_confirms_dead_dep(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_deps",
                input={
                    "verdicts": [{
                        "package_name": "old-lib",
                        "is_dead": True, "confidence": 0.9,
                        "reason": "No imports, not a build tool",
                        "remediation": "Remove from dependencies",
                        "usage_type": "unused",
                    }],
                },
            )],
            input_tokens=200, output_tokens=80,
            model="test", stop_reason="tool_use",
        )

        candidate = DependencyCandidate(
            manifest_path="requirements.txt", package_name="old-lib",
            import_names=["old_lib"], ecosystem="python", line_number=3,
        )
        results, in_tok, out_tok = await _verify_batch_async(
            mock_provider, config, [candidate],
            "old-lib>=1.0\n", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is True
        assert results[0].confidence == 0.9
        assert in_tok == 200

    @pytest.mark.asyncio
    async def test_llm_says_alive_plugin(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_deps",
                input={
                    "verdicts": [{
                        "package_name": "pytest-cov",
                        "is_dead": False, "confidence": 0.95,
                        "reason": "pytest plugin, auto-discovered",
                        "remediation": "Keep — pytest plugin",
                        "usage_type": "plugin",
                    }],
                },
            )],
            input_tokens=200, output_tokens=80,
            model="test", stop_reason="tool_use",
        )

        candidate = DependencyCandidate(
            manifest_path="requirements.txt", package_name="pytest-cov",
            import_names=["pytest_cov"], ecosystem="python", line_number=5,
        )
        results, _, _ = await _verify_batch_async(
            mock_provider, config, [candidate],
            "pytest-cov>=3.0\n", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is False
        assert results[0].usage_type == "plugin"

    @pytest.mark.asyncio
    async def test_no_tool_calls_raises(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content="I don't have a tool response",
            tool_calls=[],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="end_turn",
        )

        candidate = DependencyCandidate(
            manifest_path="requirements.txt", package_name="old-lib",
            import_names=["old_lib"], ecosystem="python", line_number=1,
        )
        with pytest.raises(RuntimeError, match="did not return verdicts"):
            await _verify_batch_async(
                mock_provider, config, [candidate],
                "old-lib\n", {},
            )


# --- TestDetectDeadDepsAsync ---

class TestDetectDeadDepsAsync:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "requirements.txt", "requests\nold-unused\n")
        _write_source(temp_dir, "src/app.py", "import requests\nrequests.get('http://example.com')\n")

        # Mock provider must handle multiple tool calls:
        # 1. resolve_import_names (Haiku) — for old-unused (requests is already imported)
        # 2. classify_deps (Haiku) — for old-unused (zero-import)
        # 3. verify_dead_deps (Sonnet) — for genuine candidates
        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            options = kwargs.get("options")
            tool_choice = options.tool_choice if options else None
            tool_name = tool_choice.get("name", "") if tool_choice else ""

            if tool_name == "resolve_import_names":
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc1", name="resolve_import_names",
                        input={"resolutions": [
                            {"package_name": "old-unused", "import_names": ["old_unused"]},
                        ]},
                    )],
                    input_tokens=100, output_tokens=50,
                    model="test", stop_reason="tool_use",
                )
            elif tool_name == "classify_deps":
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc2", name="classify_deps",
                        input={"classifications": [
                            {"package_name": "old-unused", "classification": "genuine_candidate",
                             "brief_reason": "Not a known tool"},
                        ]},
                    )],
                    input_tokens=100, output_tokens=50,
                    model="test", stop_reason="tool_use",
                )
            else:  # verify_dead_deps
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc3", name="verify_dead_deps",
                        input={"verdicts": [{
                            "package_name": "old-unused",
                            "is_dead": True, "confidence": 0.9,
                            "reason": "No imports found",
                            "remediation": "Remove dependency",
                            "usage_type": "unused",
                        }]},
                    )],
                    input_tokens=200, output_tokens=80,
                    model="test", stop_reason="tool_use",
                )

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = mock_complete

        results = await detect_dead_deps_async(mock_provider, config)
        assert len(results) == 1
        assert results[0].package_name == "old-unused"
        assert results[0].is_dead is True

    @pytest.mark.asyncio
    async def test_empty_manifests(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # No manifest files at all
        mock_provider = AsyncMock()
        results = await detect_dead_deps_async(mock_provider, config)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_zero_import_packages(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "requirements.txt", "requests\n")
        _write_source(temp_dir, "src/app.py", "import requests\n")

        mock_provider = AsyncMock()
        results = await detect_dead_deps_async(mock_provider, config)
        assert results == []


# --- TestDeadDepsAnalyzer ---

class TestDeadDepsAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_async_returns_junk_result(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "requirements.txt", "old-lib\n")
        _write_source(temp_dir, "src/app.py", "print('hello')\n")

        async def mock_complete(**kwargs):
            options = kwargs.get("options")
            tool_choice = options.tool_choice if options else None
            tool_name = tool_choice.get("name", "") if tool_choice else ""

            if tool_name == "resolve_import_names":
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc1", name="resolve_import_names",
                        input={"resolutions": [
                            {"package_name": "old-lib", "import_names": ["old_lib"]},
                        ]},
                    )],
                    input_tokens=100, output_tokens=50,
                    model="test", stop_reason="tool_use",
                )
            elif tool_name == "classify_deps":
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc2", name="classify_deps",
                        input={"classifications": [
                            {"package_name": "old-lib", "classification": "genuine_candidate",
                             "brief_reason": "Unknown package"},
                        ]},
                    )],
                    input_tokens=100, output_tokens=50,
                    model="test", stop_reason="tool_use",
                )
            else:  # verify_dead_deps
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc3", name="verify_dead_deps",
                        input={"verdicts": [{
                            "package_name": "old-lib",
                            "is_dead": True, "confidence": 0.85,
                            "reason": "No imports found",
                            "remediation": "Remove from requirements.txt",
                            "usage_type": "unused",
                        }]},
                    )],
                    input_tokens=200, output_tokens=80,
                    model="test", stop_reason="tool_use",
                )

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = mock_complete

        analyzer = DeadDepsAnalyzer()
        result = await analyzer.analyze_async(mock_provider, config)

        assert isinstance(result, JunkAnalysisResult)
        assert result.analyzer_name == "dead_deps"
        assert len(result.findings) == 1

        finding = result.findings[0]
        assert finding.source_path == "requirements.txt"
        assert finding.name == "old-lib"
        assert finding.kind == "dependency"
        assert finding.category == "dead_dependency"
        assert finding.confidence == 0.85
        assert finding.metadata["usage_type"] == "unused"

    def test_analyzer_properties(self):
        analyzer = DeadDepsAnalyzer()
        assert analyzer.name == "dead_deps"
        assert analyzer.cli_flag == "dead-deps"
        assert "dependencies" in analyzer.description.lower() or "deps" in analyzer.description.lower()

    def test_is_junk_analyzer_subclass(self):
        from osoji.junk import JunkAnalyzer
        assert issubclass(DeadDepsAnalyzer, JunkAnalyzer)
