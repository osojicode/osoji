"""Tests for cross-file dead code detection."""

import json
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.deadcode import (
    DeadCodeCandidate,
    GrepHit,
    _compute_transitive_liveness,
    _extract_context,
    _verify_batch_async,
    detect_dead_code_async,
    scan_references,
)
from osoji.llm.types import CompletionResult, ToolCall


def _write_symbols(temp_dir, source, symbols):
    """Helper to write a symbols JSON sidecar."""
    symbols_dir = temp_dir / ".osoji" / "symbols"
    # Mirror the source path structure
    sidecar = symbols_dir / (source + ".symbols.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "generated": "2025-01-01T00:00:00Z",
        "symbols": symbols,
    }
    sidecar.write_text(json.dumps(data))


def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


class TestScanReferences:
    """Tests for the scan_references() scanner."""

    def test_symbol_referenced_in_another_file(self, temp_dir):
        """Symbol referenced in another file is NOT in zero-ref list."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/utils.py", [
            {"name": "helper", "kind": "function", "line_start": 1, "line_end": 5},
        ])
        _write_source(temp_dir, "src/utils.py", "def helper():\n    pass\n")
        _write_source(temp_dir, "src/main.py", "from utils import helper\nhelper()\n")

        zero, low = scan_references(config)
        zero_names = [c.name for c in zero]
        assert "helper" not in zero_names

    def test_symbol_only_in_own_file(self, temp_dir):
        """Symbol only in its own file IS in zero-ref list."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/utils.py", [
            {"name": "lonely_func", "kind": "function", "line_start": 1, "line_end": 3},
        ])
        _write_source(temp_dir, "src/utils.py", "def lonely_func():\n    pass\n")
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        zero, low = scan_references(config)
        zero_names = [c.name for c in zero]
        assert "lonely_func" in zero_names

    def test_word_boundary_prevents_substring_match(self, temp_dir):
        """Substring match doesn't count: 'run' vs 'running'."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/engine.py", [
            {"name": "run", "kind": "function", "line_start": 1, "line_end": 3},
        ])
        _write_source(temp_dir, "src/engine.py", "def run():\n    pass\n")
        _write_source(temp_dir, "src/main.py", "running = True\n")

        zero, low = scan_references(config)
        zero_names = [c.name for c in zero]
        assert "run" in zero_names

    def test_reference_in_non_source_file_clears_zero_ref(self, temp_dir):
        """Reference in pyproject.toml clears zero-ref."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/cli.py", [
            {"name": "main", "kind": "function", "line_start": 1, "line_end": 5},
        ])
        _write_source(temp_dir, "src/cli.py", "def main():\n    pass\n")
        _write_source(temp_dir, "pyproject.toml", '[project.scripts]\nmycli = "src.cli:main"\n')

        zero, low = scan_references(config)
        zero_names = [c.name for c in zero]
        assert "main" not in zero_names

    def test_no_symbols_directory_returns_empty(self, temp_dir):
        """No .osoji/symbols/ → empty lists."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        zero, low = scan_references(config)
        assert zero == []
        assert low == []

    def test_multiple_symbols_mixed_ref_counts(self, temp_dir):
        """Multiple symbols with different ref counts get correct tier assignment."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/lib.py", [
            {"name": "used_everywhere", "kind": "function", "line_start": 1},
            {"name": "used_once", "kind": "function", "line_start": 10},
            {"name": "unused", "kind": "function", "line_start": 20},
        ])
        _write_source(temp_dir, "src/lib.py",
                       "def used_everywhere(): pass\ndef used_once(): pass\ndef unused(): pass\n")
        # Create many files referencing used_everywhere
        for i in range(10):
            _write_source(temp_dir, f"src/user_{i}.py", f"from lib import used_everywhere\nused_everywhere()\n")
        # One file referencing used_once
        _write_source(temp_dir, "src/caller.py", "from lib import used_once\nused_once()\n")

        zero, low = scan_references(config)
        zero_names = [c.name for c in zero]
        low_names = [c.name for c in low]

        assert "unused" in zero_names
        assert "used_everywhere" not in zero_names
        assert "used_everywhere" not in low_names

    def test_percentile_threshold(self, temp_dir):
        """Percentile threshold computed correctly from reference distribution."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # Create 10 symbols with ref counts 1..10
        symbols = []
        for i in range(1, 11):
            symbols.append({"name": f"func_{i}", "kind": "function", "line_start": i * 10})
        _write_symbols(temp_dir, "src/lib.py", symbols)

        content_lines = [f"def func_{i}(): pass" for i in range(1, 11)]
        _write_source(temp_dir, "src/lib.py", "\n".join(content_lines) + "\n")

        # Create reference files: func_i is referenced in i separate files
        for i in range(1, 11):
            for j in range(i):
                _write_source(temp_dir, f"src/ref_{i}_{j}.py", f"func_{i}()\n")

        zero, low = scan_references(config)
        # 10th percentile of [1,2,3,4,5,6,7,8,9,10] → index 0 → value 1
        # So threshold = 1, meaning func_1 (ref_count=1) should be in low_ref
        low_names = [c.name for c in low]
        assert "func_1" in low_names
        # func_2+ should NOT be in low_ref (ref_count > threshold)
        for i in range(2, 11):
            assert f"func_{i}" not in low_names


class TestGrepHitContext:
    """Tests for grep hit context extraction."""

    def test_low_ref_includes_grep_hits(self, temp_dir):
        """Low-ref candidate includes grep hits with context."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/lib.py", [
            {"name": "rare_func", "kind": "function", "line_start": 1},
        ])
        _write_source(temp_dir, "src/lib.py", "def rare_func(): pass\n")
        # Only one reference — ensure it ends up as low-ref
        lines = ["# line 1", "# line 2", "# line 3", "# line 4", "# line 5",
                 "rare_func()", "# line 7", "# line 8", "# line 9", "# line 10", "# line 11"]
        _write_source(temp_dir, "src/caller.py", "\n".join(lines) + "\n")

        zero, low = scan_references(config)
        # With only one non-zero ref count, threshold should include it
        low_by_name = {c.name: c for c in low}
        assert "rare_func" in low_by_name
        candidate = low_by_name["rare_func"]
        assert len(candidate.grep_hits) > 0
        hit = candidate.grep_hits[0]
        assert hit.file_path == "src/caller.py"
        assert hit.line_number == 6
        assert "rare_func()" in hit.context

    def test_context_near_file_start(self, temp_dir):
        """Context extraction works near start of file."""
        lines = ["match_line", "line2", "line3"]
        ctx = _extract_context(lines, 1, radius=5)
        assert "match_line" in ctx
        assert ">>>" in ctx  # marker for matched line

    def test_context_near_file_end(self, temp_dir):
        """Context extraction works near end of file."""
        lines = ["line1", "line2", "match_line"]
        ctx = _extract_context(lines, 3, radius=5)
        assert "match_line" in ctx
        assert ">>>" in ctx


class TestVerifyBatch:
    """Tests for LLM batch verification of dead code candidates."""

    @pytest.fixture
    def mock_provider(self):
        provider = AsyncMock()
        return provider

    @pytest.fixture
    def config(self, temp_dir):
        return Config(root_path=temp_dir, respect_gitignore=False)

    @pytest.mark.asyncio
    async def test_single_zero_ref_confirmed_dead(self, mock_provider, config):
        """LLM confirms dead for single zero-ref in a batch."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "old_helper",
                        "is_dead": True, "confidence": 0.95,
                        "reason": "No references, no decorators, not a dunder",
                        "remediation": "Remove function",
                    }],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )
        candidate = DeadCodeCandidate(
            source_path="src/utils.py", name="old_helper",
            kind="function", line_start=10, line_end=20, ref_count=0,
        )
        results, in_tokens, out_tokens = await _verify_batch_async(
            mock_provider, config, [candidate],
            "def old_helper():\n    pass\n", "Shadow doc text", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is True
        assert results[0].confidence == 0.95
        assert in_tokens == 100
        assert out_tokens == 50

    @pytest.mark.asyncio
    async def test_single_zero_ref_alive_with_decorator(self, mock_provider, config):
        """LLM says alive for zero-ref with framework decorator."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "index",
                        "is_dead": False, "confidence": 0.9,
                        "reason": "Has @app.route decorator — framework dispatch",
                        "remediation": "Keep — used by framework",
                    }],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )
        candidate = DeadCodeCandidate(
            source_path="src/views.py", name="index",
            kind="function", line_start=5, line_end=15, ref_count=0,
        )
        results, _, _ = await _verify_batch_async(
            mock_provider, config, [candidate],
            "@app.route('/')\ndef index():\n    return 'hi'\n", "", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is False

    @pytest.mark.asyncio
    async def test_multiple_symbols_in_batch(self, mock_provider, config):
        """Batch with multiple symbols returns verdicts for each."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [
                        {
                            "symbol_name": "dead_func",
                            "is_dead": True, "confidence": 0.9,
                            "reason": "No references, no alive pathway",
                            "remediation": "Remove function",
                        },
                        {
                            "symbol_name": "alive_fixture",
                            "is_dead": False, "confidence": 0.95,
                            "reason": "pytest fixture — used by framework",
                            "remediation": "Keep — pytest fixture",
                        },
                        {
                            "symbol_name": "cli_command",
                            "is_dead": False, "confidence": 0.85,
                            "reason": "Click command — convention dispatch",
                            "remediation": "Keep — Click CLI command",
                        },
                    ],
                },
            )],
            input_tokens=300, output_tokens=150,
            model="test", stop_reason="tool_use",
        )
        candidates = [
            DeadCodeCandidate(
                source_path="src/lib.py", name="dead_func",
                kind="function", line_start=1, line_end=5, ref_count=0,
            ),
            DeadCodeCandidate(
                source_path="src/lib.py", name="alive_fixture",
                kind="function", line_start=10, line_end=15, ref_count=0,
            ),
            DeadCodeCandidate(
                source_path="src/lib.py", name="cli_command",
                kind="function", line_start=20, line_end=25, ref_count=0,
            ),
        ]
        results, in_tokens, out_tokens = await _verify_batch_async(
            mock_provider, config, candidates,
            "def dead_func(): pass\ndef alive_fixture(): pass\ndef cli_command(): pass\n",
            "", {},
        )
        assert len(results) == 3
        result_by_name = {r.name: r for r in results}
        assert result_by_name["dead_func"].is_dead is True
        assert result_by_name["alive_fixture"].is_dead is False
        assert result_by_name["cli_command"].is_dead is False
        assert in_tokens == 300
        assert out_tokens == 150

    @pytest.mark.asyncio
    async def test_low_ref_all_comments_dead(self, mock_provider, config):
        """LLM confirms dead when all grep hits are comments."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "legacy_func",
                        "is_dead": True, "confidence": 0.85,
                        "reason": "All references are in comments",
                        "remediation": "Remove function and clean up comments",
                    }],
                },
            )],
            input_tokens=200, output_tokens=60,
            model="test", stop_reason="tool_use",
        )
        candidate = DeadCodeCandidate(
            source_path="src/old.py", name="legacy_func",
            kind="function", line_start=1, line_end=5, ref_count=1,
            grep_hits=[GrepHit(
                file_path="src/main.py", line_number=10,
                context="   10 | # TODO: remove legacy_func usage",
            )],
        )
        results, _, _ = await _verify_batch_async(
            mock_provider, config, [candidate],
            "def legacy_func(): pass\n", "", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is True

    @pytest.mark.asyncio
    async def test_low_ref_real_import_alive(self, mock_provider, config):
        """LLM says alive when one hit is a real import."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "parse_config",
                        "is_dead": False, "confidence": 0.95,
                        "reason": "One hit is a real import statement",
                        "remediation": "Keep — actively imported and used",
                    }],
                },
            )],
            input_tokens=200, output_tokens=60,
            model="test", stop_reason="tool_use",
        )
        candidate = DeadCodeCandidate(
            source_path="src/utils.py", name="parse_config",
            kind="function", line_start=1, line_end=10, ref_count=1,
            grep_hits=[GrepHit(
                file_path="src/app.py", line_number=3,
                context="    3 | from utils import parse_config",
            )],
        )
        results, _, _ = await _verify_batch_async(
            mock_provider, config, [candidate],
            "def parse_config(): pass\n", "", {},
        )
        assert len(results) == 1
        assert results[0].is_dead is False

    @pytest.mark.asyncio
    async def test_no_tool_calls_raises(self, mock_provider, config):
        """RuntimeError raised when LLM returns no verdicts."""
        mock_provider.complete.return_value = CompletionResult(
            content="I can't determine this.",
            tool_calls=[],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="end_turn",
        )
        candidate = DeadCodeCandidate(
            source_path="src/utils.py", name="mystery",
            kind="function", line_start=1, line_end=5, ref_count=0,
        )
        with pytest.raises(RuntimeError, match="did not return verdicts"):
            await _verify_batch_async(
                mock_provider, config, [candidate],
                "def mystery(): pass\n", "", {},
            )

    @pytest.mark.asyncio
    async def test_max_tokens_scales_with_batch_size(self, mock_provider, config):
        """max_tokens in CompletionOptions scales with number of candidates."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [
                        {
                            "symbol_name": f"func_{i}",
                            "is_dead": True, "confidence": 0.9,
                            "reason": "No references",
                            "remediation": "Remove",
                        }
                        for i in range(8)
                    ],
                },
            )],
            input_tokens=500, output_tokens=300,
            model="test", stop_reason="tool_use",
        )
        candidates = [
            DeadCodeCandidate(
                source_path="src/lib.py", name=f"func_{i}",
                kind="function", line_start=i * 10, line_end=i * 10 + 5, ref_count=0,
            )
            for i in range(8)
        ]
        await _verify_batch_async(
            mock_provider, config, candidates,
            "# file content", "", {},
        )
        # 8 candidates * 250 = 2000
        call_args = mock_provider.complete.call_args
        options = call_args.kwargs.get("options") or call_args[1].get("options")
        assert options.max_tokens == 2000

    @pytest.mark.asyncio
    async def test_completeness_validator_is_passed(self, mock_provider, config):
        """CompletionOptions includes a tool_input_validator for completeness."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "func_a",
                        "is_dead": True, "confidence": 0.9,
                        "reason": "No references",
                        "remediation": "Remove",
                    }],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )
        candidate = DeadCodeCandidate(
            source_path="src/lib.py", name="func_a",
            kind="function", line_start=1, line_end=5, ref_count=0,
        )
        await _verify_batch_async(
            mock_provider, config, [candidate],
            "def func_a(): pass\n", "", {},
        )
        call_args = mock_provider.complete.call_args
        options = call_args.kwargs.get("options") or call_args[1].get("options")
        assert len(options.tool_input_validators) == 2

        # The first validator should pass when all symbols are present
        validator = options.tool_input_validators[0]
        errs = validator("verify_dead_code", {
            "verdicts": [{"symbol_name": "func_a"}],
        })
        assert errs == []

        # The validator should fail when symbols are missing
        errs = validator("verify_dead_code", {"verdicts": []})
        assert len(errs) == 1
        assert "func_a" in errs[0]


class TestDetectDeadCodeAsync:
    """Integration test for full pipeline with mock LLM."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        """Full pipeline: all candidates (zero-ref + low-ref) go through LLM batch."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        # Set up symbols: one zero-ref, one with one reference
        _write_symbols(temp_dir, "src/lib.py", [
            {"name": "dead_func", "kind": "function", "line_start": 1, "line_end": 3},
            {"name": "maybe_dead", "kind": "function", "line_start": 5, "line_end": 8},
        ])
        _write_source(temp_dir, "src/lib.py",
                       "def dead_func(): pass\n\ndef maybe_dead(): pass\n")
        # Reference maybe_dead in one file
        _write_source(temp_dir, "src/user.py", "# maybe_dead is mentioned here\n")

        # Mock LLM provider — returns batch verdicts
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [
                        {
                            "symbol_name": "dead_func",
                            "is_dead": True, "confidence": 0.9,
                            "reason": "No references, no alive pathway",
                            "remediation": "Remove function",
                        },
                        {
                            "symbol_name": "maybe_dead",
                            "is_dead": True, "confidence": 0.8,
                            "reason": "Reference is only in a comment",
                            "remediation": "Remove function",
                        },
                    ],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )

        results, _ast_keys = await detect_dead_code_async(
            mock_provider, config,
        )

        # Both should be in results (both dead via LLM)
        dead_names = [r.name for r in results if r.is_dead]
        assert "dead_func" in dead_names
        assert "maybe_dead" in dead_names

        # dead_func now goes through LLM — confidence should be from LLM, not 1.0
        result_by_name = {r.name: r for r in results}
        dead_func_result = result_by_name["dead_func"]
        assert dead_func_result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_zero_ref_alive_through_llm(self, temp_dir):
        """Zero-ref symbol correctly identified as alive by LLM (no false positive)."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/views.py", [
            {"name": "index", "kind": "function", "line_start": 1, "line_end": 5},
        ])
        _write_source(temp_dir, "src/views.py",
                       "@app.route('/')\ndef index():\n    return 'hi'\n")
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_code",
                input={
                    "verdicts": [{
                        "symbol_name": "index",
                        "is_dead": False, "confidence": 0.95,
                        "reason": "Has @app.route — framework dispatch",
                        "remediation": "Keep — used by framework",
                    }],
                },
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )

        results, _ast_keys = await detect_dead_code_async(
            mock_provider, config,
        )

        # index should NOT appear in dead results
        dead_names = [r.name for r in results if r.is_dead]
        assert "index" not in dead_names

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty(self, temp_dir):
        """No symbols data → empty results."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # No .osoji/symbols/ at all

        mock_provider = AsyncMock()

        results, _ast_keys = await detect_dead_code_async(
            mock_provider, config,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_batching_groups_by_file(self, temp_dir):
        """Candidates from the same file are batched together."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/a.py", [
            {"name": "func_a1", "kind": "function", "line_start": 1},
            {"name": "func_a2", "kind": "function", "line_start": 10},
        ])
        _write_symbols(temp_dir, "src/b.py", [
            {"name": "func_b1", "kind": "function", "line_start": 1},
        ])
        _write_source(temp_dir, "src/a.py", "def func_a1(): pass\ndef func_a2(): pass\n")
        _write_source(temp_dir, "src/b.py", "def func_b1(): pass\n")
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        call_batches = []

        mock_provider = AsyncMock()

        async def mock_complete(messages, system, options):
            # Extract expected names from the validator
            validator = options.tool_input_validators[0]
            # Probe the validator to find expected names
            errs = validator("verify_dead_code", {"verdicts": []})
            names = set()
            for err in errs:
                # "Missing verdict for symbol 'X'"
                name = err.split("'")[1]
                names.add(name)
            call_batches.append(names)

            verdicts = [
                {
                    "symbol_name": n,
                    "is_dead": True, "confidence": 0.9,
                    "reason": "No references",
                    "remediation": "Remove",
                }
                for n in names
            ]
            return CompletionResult(
                content=None,
                tool_calls=[ToolCall(
                    id="tc1", name="verify_dead_code",
                    input={"verdicts": verdicts},
                )],
                input_tokens=100, output_tokens=50,
                model="test", stop_reason="tool_use",
            )

        mock_provider.complete = mock_complete

        await detect_dead_code_async(mock_provider, config)

        # Should have 2 batches: one for src/a.py (2 symbols), one for src/b.py (1 symbol)
        assert len(call_batches) == 2
        batch_sets = [frozenset(b) for b in call_batches]
        assert frozenset({"func_a1", "func_a2"}) in batch_sets
        assert frozenset({"func_b1"}) in batch_sets


class TestTransitiveLiveness:
    """Tests for _compute_transitive_liveness()."""

    def test_transitive_liveness_includes_last_line(self):
        """Constant used on the last line of a function should be found.

        LLM-extracted line_end values are commonly 1 line short of the actual
        function body.  The +1 padding on line_end in _compute_transitive_liveness
        compensates for this, ensuring the real last line is scanned.
        """
        # Simulate LLM reporting line_end=4 when the function actually ends
        # at line 5.  Without +1 padding, line 5 (where _HELPER is used)
        # would not be scanned and _HELPER would appear dead.
        symbols = [
            ("_HELPER", 1, 1),       # line 1: _HELPER = "value"
            ("get_things", 3, 4),    # LLM says lines 3-4, actual body is 3-5
        ]
        file_lines = [
            '_HELPER = "value"',         # line 1
            '',                          # line 2
            'def get_things():',         # line 3
            '    data = process()',       # line 4 (LLM thinks this is last line)
            '    return _HELPER',        # line 5 (actual last line, uses _HELPER)
            '',                          # line 6
        ]
        alive = _compute_transitive_liveness(
            symbols, file_lines,
            has_external_refs=lambda name: name == "get_things",
        )
        assert "_HELPER" in alive, "constant on last line should be transitively alive"
