"""Behavior-preservation test for the V1-3 Phase 3 debris cutover.

The legacy ``_verify_debris_findings_async`` was replaced by the unified Triage
stage. None of the prompt_regression fixtures exercise that path (they hit the
detector *propose* steps, which migrate in V1-5), so this deterministic test is
the cutover's preservation gate: given canned verdicts, the new path must
suppress exactly the findings the old confirmed-false-positive logic did
(verdict == "dismissed" → suppressed), and it must use the *preserved legacy
debris prompt* (decision 2: re-plumbing, not re-rubric).
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from osoji.audit import _run_phase3_async
from osoji.config import Config
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import DEBRIS_TRIAGE_SYSTEM_PROMPT


class FakeFacts:
    """FactsDB stand-in: every symbol has one cross-file reference."""

    def cross_file_references(self, symbol, source_path):
        return [{"file": "src/y.py", "kind": "import", "context": "uses it", "resolves_to_source": True}]


class FakeProvider:
    def __init__(self, result):
        self._result = result
        self.calls = 0
        self.last_system = None

    async def complete(self, messages, system, options):
        self.calls += 1
        self.last_system = system
        return self._result

    async def close(self):
        pass


def _verdicts_result(verdicts):
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id="tc1", name="submit_triage_verdicts", input={"verdicts": verdicts})],
        input_tokens=120,
        output_tokens=60,
        model="test",
        stop_reason="tool_use",
    )


def _debris(category, description, **over):
    d = {
        "source": "src/x.py",
        "source_path": Path("src/x.py"),
        "category": category,
        "line_start": 10,
        "line_end": 12,
        "severity": "warning",
        "description": description,
    }
    d.update(over)
    return d


def _run(config, raw, provider):
    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.triage.create_runtime", return_value=(provider, MagicMock())):
        return asyncio.run(_run_phase3_async(config, raw, MagicMock(), False))


def test_dismissed_verdicts_suppress_correct_indices(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [
        _debris("dead_code", "`old_helper` is defined but never used"),     # idx0 → claim0
        _debris("commented_out_code", "a dead code block"),                 # idx1 ineligible
        _debris("latent_bug", "`Foo` accessed but has no such attribute"),  # idx2 → claim1
    ]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9, "reasoning": "alive"},
        {"batch_index": 1, "verdict": "confirmed", "confidence": 0.8, "reasoning": "real bug"},
    ]))

    suppressed, phase_tokens = _run(config, raw, provider)

    # Only the dismissed dead_code finding (raw index 0) is suppressed;
    # the ineligible block (1) and the confirmed latent_bug (2) are kept.
    assert suppressed == {0}
    assert phase_tokens == (120, 60)
    assert provider.calls == 1


def test_ineligible_only_makes_no_llm_call(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [
        _debris("stale_comment", "comment is stale"),  # no cross_file flag → ineligible
        _debris("misleading_docstring", "docstring drifted"),
    ]
    provider = FakeProvider(_verdicts_result([]))

    suppressed, phase_tokens = _run(config, raw, provider)

    assert suppressed == set()
    assert phase_tokens == (0, 0)
    assert provider.calls == 0


def test_cutover_uses_preserved_legacy_debris_prompt(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [_debris("dead_code", "`old_helper` is defined but never used")]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "confirmed", "confidence": 1.0, "reasoning": "dead"},
    ]))

    _run(config, raw, provider)

    # Re-plumbing: the debris claim call uses the legacy prompt verbatim, NOT the
    # unified three-gap rubric. This is what makes the mock-equivalence sufficient.
    assert provider.last_system == DEBRIS_TRIAGE_SYSTEM_PROMPT
    assert "code debris findings are genuine or false positives" in provider.last_system
