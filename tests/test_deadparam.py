"""Tests for dead parameter detection (no LLM calls — mocked)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osoji.config import Config
from osoji.deadparam import (
    CallSite,
    DeadParamCandidate,
    DeadParameterAnalyzer,
    DeadParamVerification,
    scan_dead_param_candidates,
)
from osoji.junk import JunkAnalysisResult, JunkFinding


# --- Helpers ---

def _write_shadow(temp_dir, source):
    shadow_dir = temp_dir / ".osoji" / "shadow"
    shadow_file = shadow_dir / (source + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    shadow_file.write_text(f"# {source}\n@source-hash: abc\n\nShadow doc.")


def _write_source(temp_dir, path, content="# placeholder\n"):
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _write_symbols(temp_dir, source, symbols, file_role="service"):
    symbols_dir = temp_dir / ".osoji" / "symbols"
    symbols_file = symbols_dir / (source + ".symbols.json")
    symbols_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc",
        "file_role": file_role,
        "symbols": symbols,
    }
    symbols_file.write_text(json.dumps(data))


def _write_facts(temp_dir, source, imports=None, exports=None, calls=None):
    facts_dir = temp_dir / ".osoji" / "facts"
    facts_file = facts_dir / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc",
        "imports": imports or [],
        "exports": exports or [],
        "calls": calls or [],
        "string_literals": [],
    }
    facts_file.write_text(json.dumps(data))


# --- Phase 1: scan_dead_param_candidates ---

class TestScanCandidates:
    def test_function_with_optional_params_and_callers(self, temp_dir):
        """Function with optional params (from symbols) and callers produces candidates."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        # Write a source file with a function having optional params
        _write_source(temp_dir, "src/scorecard.py", "\n".join([
            "from .config import Config",
            "",
            "def build_scorecard(",
            "    config: Config,",
            "    results: list,",
            "    dead_code_results: list | None = None,",
            ") -> dict:",
            "    if dead_code_results is not None:",
            "        pass",
            "    return {}",
        ]))
        _write_symbols(temp_dir, "src/scorecard.py", [
            {"name": "build_scorecard", "kind": "function", "line_start": 3,
             "line_end": 10, "visibility": "public",
             "parameters": [
                 {"name": "config", "optional": False},
                 {"name": "results", "optional": False},
                 {"name": "dead_code_results", "optional": True},
             ]},
        ])

        # Write a caller file
        _write_source(temp_dir, "src/audit.py", "\n".join([
            "from .scorecard import build_scorecard",
            "",
            "def run_audit():",
            "    sc = build_scorecard(config, results)",
            "    return sc",
        ]))
        _write_facts(temp_dir, "src/scorecard.py", exports=[{"name": "build_scorecard"}])
        _write_facts(temp_dir, "src/audit.py", imports=[
            {"source": ".scorecard", "names": ["build_scorecard"]},
        ])

        # Need git for list_repo_files — mock it
        with patch("osoji.deadparam.list_repo_files") as mock_list:
            mock_list.return_value = (
                [temp_dir / "src/scorecard.py", temp_dir / "src/audit.py"],
                [],
            )
            candidates = scan_dead_param_candidates(config)

        assert len(candidates) >= 1
        param_names = [c.param_name for c in candidates]
        assert "dead_code_results" in param_names
        # Required params should not be candidates
        assert "config" not in param_names
        assert "results" not in param_names

    def test_function_with_no_optional_params_skipped(self, temp_dir):
        """Function with no optional params (in symbols) is not a candidate."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_source(temp_dir, "src/utils.py", "\n".join([
            "def add(a: int, b: int) -> int:",
            "    return a + b",
        ]))
        _write_symbols(temp_dir, "src/utils.py", [
            {"name": "add", "kind": "function", "line_start": 1,
             "line_end": 2, "visibility": "public",
             "parameters": [
                 {"name": "a", "optional": False},
                 {"name": "b", "optional": False},
             ]},
        ])
        _write_facts(temp_dir, "src/utils.py", exports=[{"name": "add"}])
        _write_facts(temp_dir, "src/caller.py", imports=[
            {"source": ".utils", "names": ["add"]},
        ])

        with patch("osoji.deadparam.list_repo_files") as mock_list:
            mock_list.return_value = ([temp_dir / "src/utils.py"], [])
            candidates = scan_dead_param_candidates(config)

        assert len(candidates) == 0

    def test_function_with_no_callers_skipped(self, temp_dir):
        """Function with optional params but no callers is skipped (deadcode handles it)."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_source(temp_dir, "src/orphan.py", "\n".join([
            "def lonely_func(x: int = 0) -> int:",
            "    return x",
        ]))
        _write_symbols(temp_dir, "src/orphan.py", [
            {"name": "lonely_func", "kind": "function", "line_start": 1,
             "line_end": 2, "visibility": "public",
             "parameters": [
                 {"name": "x", "optional": True},
             ]},
        ])
        _write_facts(temp_dir, "src/orphan.py", exports=[{"name": "lonely_func"}])
        # No other file imports src/orphan.py

        with patch("osoji.deadparam.list_repo_files") as mock_list:
            mock_list.return_value = ([temp_dir / "src/orphan.py"], [])
            candidates = scan_dead_param_candidates(config)

        assert len(candidates) == 0

    def test_internal_functions_skipped(self, temp_dir):
        """Internal/private functions are not candidates."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_source(temp_dir, "src/utils.py", "\n".join([
            "def _helper(x: int = 0) -> int:",
            "    return x",
        ]))
        _write_symbols(temp_dir, "src/utils.py", [
            {"name": "_helper", "kind": "function", "line_start": 1,
             "line_end": 2, "visibility": "internal",
             "parameters": [
                 {"name": "x", "optional": True},
             ]},
        ])
        _write_facts(temp_dir, "src/utils.py", exports=[{"name": "_helper"}])

        with patch("osoji.deadparam.list_repo_files") as mock_list:
            mock_list.return_value = ([temp_dir / "src/utils.py"], [])
            candidates = scan_dead_param_candidates(config)

        assert len(candidates) == 0

    def test_symbols_without_parameters_skipped(self, temp_dir):
        """Old symbols without parameters field are gracefully skipped."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_source(temp_dir, "src/utils.py", "\n".join([
            "def func(x: int = 0) -> int:",
            "    return x",
        ]))
        # No parameters field — backward compat
        _write_symbols(temp_dir, "src/utils.py", [
            {"name": "func", "kind": "function", "line_start": 1,
             "line_end": 2, "visibility": "public"},
        ])
        _write_facts(temp_dir, "src/utils.py", exports=[{"name": "func"}])
        _write_facts(temp_dir, "src/caller.py", imports=[
            {"source": ".utils", "names": ["func"]},
        ])

        with patch("osoji.deadparam.list_repo_files") as mock_list:
            mock_list.return_value = ([temp_dir / "src/utils.py"], [])
            candidates = scan_dead_param_candidates(config)

        assert len(candidates) == 0


# --- Phase 2: LLM verification (mocked) ---

class TestVerification:
    def test_dead_verdict_produces_finding(self):
        """LLM returns dead verdict -> DeadParamVerification with is_dead=True."""
        from osoji.deadparam import _verify_batch_async
        from osoji.llm.types import CompletionResult, ToolCall

        candidates = [
            DeadParamCandidate(
                source_path="src/scorecard.py",
                function_name="build_scorecard",
                param_name="dead_code_results",
                param_line=6,
                has_default=True,
                call_sites=[
                    CallSite("src/audit.py", 10, "    sc = build_scorecard(config, results)"),
                ],
            ),
        ]

        mock_result = CompletionResult(
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="verify_dead_parameters",
                    input={
                        "verdicts": [{
                            "function_name": "build_scorecard",
                            "parameter_name": "dead_code_results",
                            "is_dead": True,
                            "confidence": 0.95,
                            "reason": "No caller passes this parameter",
                            "remediation": "Remove parameter and gated branches",
                            "gated_line_ranges": [
                                {"line_start": 8, "line_end": 9},
                            ],
                        }],
                    },
                ),
            ],
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514",
            stop_reason="tool_use",
        )

        provider = AsyncMock()
        provider.complete = AsyncMock(return_value=mock_result)
        config = MagicMock()
        config.model = "claude-sonnet-4-20250514"

        import asyncio
        verifications, in_tok, out_tok = asyncio.run(
            _verify_batch_async(provider, config, candidates, "file content", "shadow content")
        )

        assert len(verifications) == 1
        v = verifications[0]
        assert v.is_dead is True
        assert v.param_name == "dead_code_results"
        assert v.function_name == "build_scorecard"
        assert v.confidence == 0.95
        assert v.gated_line_ranges == [(8, 9)]

    def test_alive_verdict(self):
        """LLM returns alive verdict -> DeadParamVerification with is_dead=False."""
        from osoji.deadparam import _verify_batch_async
        from osoji.llm.types import CompletionResult, ToolCall

        candidates = [
            DeadParamCandidate(
                source_path="src/module.py",
                function_name="process",
                param_name="verbose",
                param_line=3,
                has_default=True,
                call_sites=[
                    CallSite("src/caller.py", 5, "    process(data, verbose=True)"),
                ],
            ),
        ]

        mock_result = CompletionResult(
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="verify_dead_parameters",
                    input={
                        "verdicts": [{
                            "function_name": "process",
                            "parameter_name": "verbose",
                            "is_dead": False,
                            "confidence": 0.99,
                            "reason": "Caller at src/caller.py:5 passes verbose=True",
                            "remediation": "Keep — parameter is used",
                        }],
                    },
                ),
            ],
            input_tokens=80,
            output_tokens=40,
            model="claude-sonnet-4-20250514",
            stop_reason="tool_use",
        )

        provider = AsyncMock()
        provider.complete = AsyncMock(return_value=mock_result)
        config = MagicMock()
        config.model = "claude-sonnet-4-20250514"

        import asyncio
        verifications, _, _ = asyncio.run(
            _verify_batch_async(provider, config, candidates, "file content", "shadow content")
        )

        assert len(verifications) == 1
        assert verifications[0].is_dead is False


# --- Analyzer class ---

class TestAnalyzerClass:
    def test_name(self):
        analyzer = DeadParameterAnalyzer()
        assert analyzer.name == "dead_params"

    def test_cli_flag(self):
        analyzer = DeadParameterAnalyzer()
        assert analyzer.cli_flag == "dead-params"

    def test_description(self):
        analyzer = DeadParameterAnalyzer()
        assert "dead" in analyzer.description.lower()
        assert "parameter" in analyzer.description.lower()

    def test_category_mapping(self):
        """Analyzer produces JunkFindings with category='dead_parameter'."""
        analyzer = DeadParameterAnalyzer()

        async def mock_detect(*args, **kwargs):
            return [
                DeadParamVerification(
                    source_path="src/mod.py",
                    function_name="func",
                    param_name="unused",
                    is_dead=True,
                    confidence=0.9,
                    reason="Never passed",
                    remediation="Remove",
                    gated_line_ranges=[(10, 15)],
                ),
            ]

        with patch("osoji.deadparam.detect_dead_params_async", side_effect=mock_detect):
            import asyncio
            result = asyncio.run(analyzer.analyze_async(
                MagicMock(), MagicMock(), MagicMock(), None
            ))

        assert len(result.findings) == 1
        assert result.findings[0].category == "dead_parameter"
        assert result.findings[0].name == "func.unused"
        assert result.findings[0].metadata["function_name"] == "func"
        assert result.findings[0].metadata["gated_lines"] == [[10, 15]]
        assert result.analyzer_name == "dead_params"


# --- Integration with scorecard ---

class TestScorecardIntegration:
    def test_dead_param_findings_in_junk_metrics(self, temp_dir):
        """Dead parameter findings appear in scorecard junk metrics."""
        from osoji.scorecard import build_scorecard

        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/scorecard.py")
        _write_source(temp_dir, "src/scorecard.py", "\n".join(f"line {i}" for i in range(50)))

        junk_results = {
            "dead_params": JunkAnalysisResult(
                findings=[
                    JunkFinding(
                        source_path="src/scorecard.py",
                        name="build_scorecard.dead_code_results",
                        kind="parameter",
                        category="dead_parameter",
                        line_start=20,
                        line_end=30,
                        confidence=0.95,
                        reason="Never passed by any caller",
                        remediation="Remove parameter and gated branches",
                        original_purpose="parameter `dead_code_results` of `build_scorecard`",
                        metadata={"function_name": "build_scorecard", "gated_lines": [[20, 30]]},
                    ),
                ],
                total_candidates=5,
                analyzer_name="dead_params",
            ),
        }
        sc = build_scorecard(config, [], junk_results=junk_results)
        assert sc.junk_total_lines == 11  # lines 20-30
        assert "dead_params" in sc.junk_sources
        assert sc.junk_by_category.get("dead_parameter", 0) == 1
