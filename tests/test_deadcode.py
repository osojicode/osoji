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


def _triage_result(verdicts):
    """A canned submit_triage_verdicts completion."""
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(
            id="tc1", name="submit_triage_verdicts",
            input={"verdicts": verdicts},
        )],
        input_tokens=100, output_tokens=50,
        model="test", stop_reason="tool_use",
    )


class TestDetectDeadCodeAsync:
    """Integration tests for the unified Claim Builder + Triage pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        """All candidates (zero-ref + low-ref) are decided through Triage claims."""
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

        # Candidate order is deterministic: zero-ref candidates precede low-ref,
        # so dead_func is batch_index 0 and maybe_dead is batch_index 1.
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = _triage_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9,
             "reasoning": "No references, no alive pathway",
             "suggested_fix": "Remove function"},
            {"batch_index": 1, "verdict": "confirmed", "confidence": 0.8,
             "reasoning": "Reference is only in a comment",
             "suggested_fix": "Remove function"},
        ])

        results, mechanical_keys = await detect_dead_code_async(mock_provider, config)

        confirmed = {f.symbol: f for f in results if f.verdict == "confirmed"}
        assert set(confirmed) == {"dead_func", "maybe_dead"}
        assert confirmed["dead_func"].confidence == 0.9
        assert confirmed["dead_func"].triage_reasoning == "No references, no alive pathway"
        assert confirmed["dead_func"].gap_type == "reachability"
        assert confirmed["dead_func"].detector == "deadcode:dead_symbol"
        # Nothing was AST-proven here — both went through the LLM
        assert mechanical_keys == set()

    @pytest.mark.asyncio
    async def test_zero_ref_alive_through_llm(self, temp_dir):
        """Zero-ref symbol correctly dismissed by Triage (no false positive)."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/views.py", [
            {"name": "index", "kind": "function", "line_start": 1, "line_end": 5},
        ])
        _write_source(temp_dir, "src/views.py",
                       "@app.route('/')\ndef index():\n    return 'hi'\n")
        _write_source(temp_dir, "src/main.py", "print('hello')\n")

        mock_provider = AsyncMock()
        mock_provider.complete.return_value = _triage_result([
            {"batch_index": 0, "verdict": "dismissed", "confidence": 0.95,
             "reasoning": "Has @app.route — framework dispatch"},
        ])

        results, _mechanical_keys = await detect_dead_code_async(mock_provider, config)

        confirmed = [f.symbol for f in results if f.verdict == "confirmed"]
        assert "index" not in confirmed
        # The dismissal itself is recorded, not silently dropped
        dismissed = [f.symbol for f in results if f.verdict == "dismissed"]
        assert "index" in dismissed

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty(self, temp_dir):
        """No symbols data → empty results."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # No .osoji/symbols/ at all

        mock_provider = AsyncMock()

        results, _mechanical_keys = await detect_dead_code_async(
            mock_provider, config,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_small_claim_sets_pack_into_one_call(self, temp_dir):
        """Claims from several files pack into a single Triage call (chunk <= 12)."""
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

        batch_sizes = []
        mock_provider = AsyncMock()

        async def mock_complete(messages, system, options):
            # Probe the completeness validator to learn the batch size
            validator = options.tool_input_validators[0]
            n = len(validator("submit_triage_verdicts", {"verdicts": []}))
            batch_sizes.append(n)
            return _triage_result([
                {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                 "reasoning": "No references"}
                for i in range(n)
            ])

        mock_provider.complete = mock_complete

        results, _mechanical_keys = await detect_dead_code_async(mock_provider, config)

        assert batch_sizes == [3]
        assert sum(1 for f in results if f.verdict == "confirmed") == 3


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
