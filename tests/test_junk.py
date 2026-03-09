"""Tests for the unified junk code analysis framework."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.junk import (
    JunkAnalyzer,
    JunkAnalysisResult,
    JunkFinding,
    load_shadow_content,
)
from osoji.deadcode import DeadCodeAnalyzer
from osoji.plumbing import DeadPlumbingAnalyzer
from osoji.llm.types import CompletionResult, ToolCall
from osoji.rate_limiter import RateLimiter, RateLimiterConfig


# --- Helpers ---

def _write_shadow(temp_dir, source, content="# Shadow\nShadow doc content."):
    """Helper to write a shadow doc."""
    shadow_dir = temp_dir / ".osoji" / "shadow"
    shadow_file = shadow_dir / (source + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    shadow_file.write_text(content)


def _write_symbols(temp_dir, source, symbols, file_role=None):
    """Helper to write a symbols JSON sidecar."""
    symbols_dir = temp_dir / ".osoji" / "symbols"
    sidecar = symbols_dir / (source + ".symbols.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "generated": "2025-01-01T00:00:00Z",
        "symbols": symbols,
    }
    if file_role is not None:
        data["file_role"] = file_role
    sidecar.write_text(json.dumps(data))


def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


# --- JunkFinding ---

class TestJunkFinding:
    def test_construction(self):
        """JunkFinding can be constructed with all required fields."""
        finding = JunkFinding(
            source_path="src/utils.py",
            name="old_func",
            kind="function",
            category="dead_symbol",
            line_start=10,
            line_end=20,
            confidence=0.95,
            reason="No references",
            remediation="Remove function",
            original_purpose="function `old_func`",
        )
        assert finding.source_path == "src/utils.py"
        assert finding.name == "old_func"
        assert finding.kind == "function"
        assert finding.category == "dead_symbol"
        assert finding.confidence == 0.95
        assert finding.metadata == {}

    def test_metadata_default(self):
        """metadata defaults to empty dict."""
        finding = JunkFinding(
            source_path="a.py", name="x", kind="function", category="dead_symbol",
            line_start=1, line_end=None, confidence=0.9, reason="r",
            remediation="rm", original_purpose="p",
        )
        assert finding.metadata == {}

    def test_metadata_custom(self):
        """Custom metadata can be passed."""
        finding = JunkFinding(
            source_path="a.py", name="x", kind="config_field",
            category="unactuated_config", line_start=1, line_end=None,
            confidence=0.9, reason="r", remediation="rm", original_purpose="p",
            metadata={"schema_name": "MySchema"},
        )
        assert finding.metadata["schema_name"] == "MySchema"


# --- JunkAnalysisResult ---

class TestJunkAnalysisResult:
    def test_construction(self):
        result = JunkAnalysisResult(
            findings=[],
            total_candidates=5,
            analyzer_name="dead_code",
        )
        assert result.findings == []
        assert result.total_candidates == 5
        assert result.analyzer_name == "dead_code"


# --- load_shadow_content ---

class TestLoadShadowContent:
    def test_loads_existing_shadow(self, temp_dir):
        """Returns shadow content when file exists."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/utils.py", "# Utils\nHelper functions.")

        content = load_shadow_content(config, "src/utils.py")
        assert "# Utils" in content
        assert "Helper functions." in content

    def test_returns_empty_for_missing(self, temp_dir):
        """Returns empty string when shadow doesn't exist."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        content = load_shadow_content(config, "src/nonexistent.py")
        assert content == ""


# --- Analyzer registry ---

class TestAnalyzerRegistry:
    def test_dead_code_analyzer_properties(self):
        analyzer = DeadCodeAnalyzer()
        assert analyzer.name == "dead_code"
        assert analyzer.cli_flag == "dead-code"
        assert "dead code" in analyzer.description.lower()

    def test_dead_plumbing_analyzer_properties(self):
        analyzer = DeadPlumbingAnalyzer()
        assert analyzer.name == "dead_plumbing"
        assert analyzer.cli_flag == "dead-plumbing"
        assert "config" in analyzer.description.lower() or "plumbing" in analyzer.description.lower()

    def test_analyzers_are_junk_analyzer_subclasses(self):
        assert issubclass(DeadCodeAnalyzer, JunkAnalyzer)
        assert issubclass(DeadPlumbingAnalyzer, JunkAnalyzer)


# --- DeadCodeAnalyzer ---

class TestDeadCodeAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_async_returns_junk_result(self, temp_dir):
        """DeadCodeAnalyzer.analyze_async returns JunkAnalysisResult with correct mappings."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/lib.py", [
            {"name": "dead_func", "kind": "function", "line_start": 1, "line_end": 3},
        ])
        _write_source(temp_dir, "src/lib.py", "def dead_func(): pass\n")
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "dead_func",
                        "is_dead": True, "confidence": 0.9,
                        "reason": "No references",
                        "remediation": "Remove function",
                    }],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )

        rate_limiter = RateLimiter(RateLimiterConfig(
            requests_per_minute=1000,
            input_tokens_per_minute=1_000_000,
            output_tokens_per_minute=1_000_000,
        ))

        analyzer = DeadCodeAnalyzer()
        result = await analyzer.analyze_async(mock_provider, rate_limiter, config)

        assert isinstance(result, JunkAnalysisResult)
        assert result.analyzer_name == "dead_code"
        assert len(result.findings) == 1

        finding = result.findings[0]
        assert finding.source_path == "src/lib.py"
        assert finding.name == "dead_func"
        assert finding.kind == "function"
        assert finding.category == "dead_symbol"
        assert finding.confidence == 0.9
        assert finding.reason == "No references"
        assert finding.remediation == "Remove function"


# --- DeadPlumbingAnalyzer ---

class TestDeadPlumbingAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_async_returns_junk_result(self, temp_dir):
        """DeadPlumbingAnalyzer.analyze_async returns JunkAnalysisResult with correct mappings."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/trial.ts", [], file_role="schema")
        _write_source(temp_dir, "src/trial.ts",
                       "const Schema = z.object({\n  taskTimeoutMs: z.number(),\n});")
        _write_shadow(temp_dir, "src/trial.ts", "# Schema\nTimeout fields")

        _write_source(temp_dir, "src/runner.ts", "const t = config.taskTimeoutMs;\n")
        _write_shadow(temp_dir, "src/runner.ts", "# Runner\nReads config")

        mock_provider = AsyncMock()
        call_count = 0

        async def mock_complete(messages, system, options):
            nonlocal call_count
            call_count += 1
            if "extract_obligations" in (options.tool_choice or {}).get("name", ""):
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc1", name="extract_obligations",
                        input={
                            "obligations": [{
                                "field_name": "taskTimeoutMs",
                                "schema_name": "Schema",
                                "line_start": 2,
                                "line_end": 2,
                                "obligation": "Enforce task timeout",
                                "expected_actuation": "timer/deadline",
                            }],
                        },
                    )],
                    input_tokens=500, output_tokens=200,
                    model="test", stop_reason="tool_use",
                )
            else:
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc2", name="verify_actuation",
                        input={
                            "is_actuated": False,
                            "confidence": 0.9,
                            "trace": "taskTimeoutMs stored but never enforced",
                            "remediation": "Add timer enforcement",
                        },
                    )],
                    input_tokens=400, output_tokens=80,
                    model="test", stop_reason="tool_use",
                )

        mock_provider.complete = mock_complete

        rate_limiter = RateLimiter(RateLimiterConfig(
            requests_per_minute=1000,
            input_tokens_per_minute=1_000_000,
            output_tokens_per_minute=1_000_000,
        ))

        analyzer = DeadPlumbingAnalyzer()
        result = await analyzer.analyze_async(mock_provider, rate_limiter, config)

        assert isinstance(result, JunkAnalysisResult)
        assert result.analyzer_name == "dead_plumbing"
        assert result.total_candidates == 1
        assert len(result.findings) == 1

        finding = result.findings[0]
        assert finding.source_path == "src/trial.ts"
        assert finding.name == "taskTimeoutMs"
        assert finding.kind == "config_field"
        assert finding.category == "unactuated_config"
        assert finding.confidence == 0.9
        assert finding.metadata["schema_name"] == "Schema"


# --- Config path helper ---

class TestConfigJunkPath:
    def test_analysis_junk_path_for(self, temp_dir):
        """analysis_junk_path_for generates correct path."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        path = config.analysis_junk_path_for("dead_code", Path("src/utils.py"))
        expected = config.analysis_root / "junk" / "dead_code" / "src/utils.py.dead_code.json"
        assert path == expected
