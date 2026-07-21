"""Behavior-preservation test for the V1-3 Phase 3 debris cutover.

The legacy ``_verify_debris_findings_async`` was replaced by the unified Triage
stage. None of the prompt_regression fixtures exercise that path (they hit the
detector *propose* steps, which migrated in V1-5), so this deterministic test is
the cutover's preservation gate: given canned verdicts, the new path must
suppress exactly the findings the old confirmed-false-positive logic did
(verdict == "dismissed" → suppressed). Since V1-5e the call is pinned to the
unified rubric (the legacy debris prompt is retired; A/B in ab-v15e-report.md).
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from osoji.audit import _run_phase3_async
from osoji.config import Config
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import TRIAGE_SYSTEM_PROMPT


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
         patch("osoji.triage.create_runtime", return_value=(provider, MagicMock())), \
         patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
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


def test_debris_corpus_is_decided_in_bounded_chunks(temp_dir):
    # work#57: the V1-5e A/B saw a whole-corpus decide_batch (62 claims) go
    # off-by-one from ~index 5. Phase 3 must chunk like every Phase 4 analyzer
    # (decide_junk_claims, BATCH_SIZE=12) instead of one monolithic call.
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [
        _debris("dead_code", f"`helper_{i}` is defined but never used", line_start=i + 1, line_end=i + 1)
        for i in range(13)
    ]
    # The same canned result serves every chunk: batch_index 0 dismissed, the
    # rest confirmed. Chunk 1 (claims 0-11) suppresses raw index 0; chunk 2
    # (claim 12 alone) sees its only claim at batch_index 0 → also dismissed.
    provider = FakeProvider(_verdicts_result(
        [{"batch_index": 0, "verdict": "dismissed", "confidence": 0.9, "reasoning": "alive"}]
        + [{"batch_index": i, "verdict": "confirmed", "confidence": 0.8, "reasoning": "dead"}
           for i in range(1, 12)]
    ))

    suppressed, phase_tokens = _run(config, raw, provider)

    assert provider.calls == 2  # 13 claims → chunks of 12 + 1
    assert suppressed == {0, 12}
    assert phase_tokens == (240, 120)


def test_debris_triage_uses_unified_rubric(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [_debris("dead_code", "`old_helper` is defined but never used")]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "confirmed", "confidence": 1.0, "reasoning": "dead"},
    ]))

    _run(config, raw, provider)

    # V1-5e: the last legacy-prompt holdout flipped onto the unified three-gap
    # rubric, gated by the same-claims A/B in ab-v15e-report.md.
    assert provider.last_system == TRIAGE_SYSTEM_PROMPT


def test_provider_failure_records_debris_triage_degradation(temp_dir):
    """Track 2 PR-A: a Triage-seam failure keeps all findings AND is recorded.

    ``decide_junk_claims`` retries/bisects and swallows a per-chunk provider
    failure internally (findings come back undecided, verdict=None — see
    junk_triage.py) so it never raises. To exercise the seam's own
    ``except Exception`` at the ``_run_phase3_async`` level, the failure has
    to happen one step earlier: obtaining the runtime itself.
    """
    config = Config(root_path=temp_dir, respect_gitignore=False)
    config.audit_degradations = []
    raw = [_debris("dead_code", "`old_helper` is defined but never used")]

    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", side_effect=RuntimeError("boom")):
        suppressed, phase_tokens = asyncio.run(_run_phase3_async(config, raw, MagicMock(), False))

    assert suppressed == set()  # best-effort: nothing suppressed, all kept
    assert phase_tokens == (0, 0)
    assert config.audit_degradations == [{"phase": "debris-triage", "error": "boom"}]
