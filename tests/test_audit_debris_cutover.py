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
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from osoji.audit import _run_phase3_async, run_audit_async
from osoji.config import Config
from osoji.hasher import compute_file_hash, compute_impl_hash
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
        # idx1: eligible since #168, but src/x.py is not on disk and the
        # description yields no needles → require_any unmet → pass-through.
        _debris("commented_out_code", "a dead code block"),
        _debris("latent_bug", "`Foo` accessed but has no such attribute"),  # idx2 → claim1
    ]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9, "reasoning": "alive"},
        {"batch_index": 1, "verdict": "confirmed", "confidence": 0.8, "reasoning": "real bug"},
    ]))

    suppressed, phase_tokens, decided = _run(config, raw, provider)

    # Only the dismissed dead_code finding (raw index 0) is suppressed;
    # the unclaimable block (1) and the confirmed latent_bug (2) are kept.
    assert suppressed == {0}
    assert phase_tokens == (120, 60)
    assert provider.calls == 1
    # Both eligible claims land in the decided map, keyed by raw index.
    assert set(decided.keys()) == {0, 2}
    assert decided[0].verdict == "dismissed"
    assert decided[2].verdict == "confirmed"
    assert decided[2].confidence == 0.8
    assert decided[2].triage_reasoning == "real bug"


def test_unclaimable_only_makes_no_llm_call(temp_dir):
    # Since #168 every category is admitted, so the no-claims path is reached
    # only when nothing is claimable: the flagged file is absent (description
    # require_any=surrounding_code unmet) or the record carries no source.
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [
        _debris("stale_comment", "comment is stale"),  # src/x.py not on disk
        _debris("misleading_docstring", "docstring drifted", source=None, source_path=None),
    ]
    provider = FakeProvider(_verdicts_result([]))

    suppressed, phase_tokens, decided = _run(config, raw, provider)

    assert suppressed == set()
    assert phase_tokens == (0, 0)
    assert provider.calls == 0
    assert decided == {}


def test_description_family_reaches_triage_and_verdicts_land(temp_dir):
    # THE #168 behavior change: unflagged stale_comment, misleading_docstring,
    # expired_todo, and commented_out_code all build claims (real file on
    # disk) and receive verdicts; dismissed ones suppress like any debris.
    config = Config(root_path=temp_dir, respect_gitignore=False)
    src = temp_dir / "src" / "x.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("def helper():\n" + "    pass  # filler\n" * 13, encoding="utf-8")
    raw = [
        _debris("stale_comment", "comment says retries, code does not retry"),
        _debris("misleading_docstring", "docstring describes removed behavior"),
        _debris("expired_todo", "TODO(2024-01) remove after migration"),
        _debris("commented_out_code", "a commented-out block kept around"),
    ]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9,
         "reasoning": "comment is accurate at module level"},
        {"batch_index": 1, "verdict": "confirmed", "confidence": 0.85, "reasoning": "drifted"},
        {"batch_index": 2, "verdict": "confirmed", "confidence": 0.8, "reasoning": "expired"},
        {"batch_index": 3, "verdict": "confirmed", "confidence": 0.75, "reasoning": "debris"},
    ]))

    suppressed, phase_tokens, decided = _run(config, raw, provider)

    assert provider.calls == 1
    assert suppressed == {0}
    assert set(decided.keys()) == {0, 1, 2, 3}
    assert decided[1].verdict == "confirmed"
    assert decided[3].verdict == "confirmed"
    assert phase_tokens == (120, 60)


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

    suppressed, phase_tokens, decided = _run(config, raw, provider)

    assert provider.calls == 2  # 13 claims → chunks of 12 + 1
    assert suppressed == {0, 12}
    assert phase_tokens == (240, 120)
    assert len(decided) == 13


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


def test_decided_findings_carry_suggested_fix_and_severity(temp_dir):
    """The decided Finding map threads suggested_fix/severity — the product
    boundary overlay (run_audit_async) reads these to grade Phase 3 issues."""
    config = Config(root_path=temp_dir, respect_gitignore=False)
    raw = [_debris("dead_code", "`old_helper` is defined but never used", severity="warning")]
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.95,
         "reasoning": "confirmed dead", "suggested_fix": "delete `old_helper`",
         "severity": "info"},
    ]))

    suppressed, _phase_tokens, decided = _run(config, raw, provider)

    assert suppressed == set()
    finding = decided[0]
    assert finding.suggested_fix == "delete `old_helper`"
    assert finding.severity == "info"  # demote-not-drop: Triage may re-grade
    assert finding.confidence == 0.95
    assert finding.triage_reasoning == "confirmed dead"
    assert finding.id


def test_provider_failure_records_debris_triage_degradation(temp_dir):
    """A Triage-seam failure keeps all findings AND is recorded.

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
        suppressed, phase_tokens, decided = asyncio.run(_run_phase3_async(config, raw, MagicMock(), False))

    assert suppressed == set()  # best-effort: nothing suppressed, all kept
    assert phase_tokens == (0, 0)
    assert decided == {}  # no decided Findings on the failure path
    assert config.audit_degradations == [{"phase": "debris-triage", "error": "boom"}]


def test_provider_failure_without_attached_degradations_list_does_not_crash(temp_dir):
    """The getattr-absent safety path: config.audit_degradations is only
    attached by run_audit_async, so a phase called directly (as every other
    test in this module does) must not raise merely because the attribute
    doesn't exist — it should keep findings exactly as before, silently."""
    config = Config(root_path=temp_dir, respect_gitignore=False)
    assert not hasattr(config, "audit_degradations")
    raw = [_debris("dead_code", "`old_helper` is defined but never used")]

    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", side_effect=RuntimeError("boom")):
        suppressed, phase_tokens, decided = asyncio.run(_run_phase3_async(config, raw, MagicMock(), False))

    assert suppressed == set()  # best-effort: nothing suppressed, all kept
    assert phase_tokens == (0, 0)
    assert decided == {}
    assert not hasattr(config, "audit_degradations")  # getattr default: no crash, nothing created


# --- product-boundary overlay (end-to-end via run_audit_async) ----------------


def _write(temp_dir: Path, rel: str, text: str) -> None:
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_findings(temp_dir: Path, rel_path: str, findings: list[dict]) -> None:
    findings_file = temp_dir / ".osoji" / "findings" / (rel_path + ".findings.json")
    findings_file.parent.mkdir(parents=True, exist_ok=True)
    source_path = temp_dir / rel_path
    findings_file.write_text(json.dumps({
        "source": rel_path,
        "source_hash": compute_file_hash(source_path),
        "impl_hash": compute_impl_hash(),
        "generated": "2026-01-01T00:00:00Z",
        "findings": findings,
    }), encoding="utf-8")


def test_overlay_lands_on_kept_issues_end_to_end(temp_dir):
    """End-to-end (run_audit_async): a confirmed verdict's severity/suggested-fix
    /verdict/confidence/triage-reasoning land on the kept AuditIssue, additively
    (the heuristic remediation is unchanged); a dismissed verdict still
    suppresses its finding entirely, exactly as before this migration; and
    since osoji#168 the description family is triaged too — the
    commented_out_code finding carries a verdict instead of passing through,
    and the scorecard's untriaged-debris floor reads zero."""
    _write(temp_dir, "src/x.py",
           "def old_helper():\n    pass\n\n\ndef also_dead():\n    pass\n# some old code\n")
    _write_findings(temp_dir, "src/x.py", [
        {
            "category": "dead_code", "line_start": 1, "line_end": 2,
            "severity": "warning", "description": "`old_helper` is defined but never used",
        },
        {
            "category": "dead_code", "line_start": 5, "line_end": 6,
            "severity": "warning", "description": "`also_dead` is defined but never used",
        },
        {
            "category": "commented_out_code", "line_start": 8, "line_end": 8,
            "severity": "warning", "description": "a commented-out code block",
        },
    ])
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.92,
         "reasoning": "no references found", "suggested_fix": "delete `old_helper`",
         "severity": "info"},
        {"batch_index": 1, "verdict": "dismissed", "confidence": 0.9,
         "reasoning": "actually used dynamically"},
        {"batch_index": 2, "verdict": "confirmed", "confidence": 0.7,
         "reasoning": "no reference keeps this block"},
    ]))

    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, exclude={"shadow", "doc-analysis"},
        ))

    debris_issues = [i for i in result.issues if i.exclude_key == "debris"]
    assert len(debris_issues) == 2  # dismissed finding (also_dead) suppressed
    issue = next(i for i in debris_issues if "old_helper" in i.message)
    assert issue.verdict == "confirmed"
    assert issue.confidence == 0.92
    assert issue.triage_reasoning == "no references found"
    assert issue.suggested_fix == "delete `old_helper`"
    assert issue.severity == "info"  # re-graded from the heuristic "warning"
    assert issue.finding_id
    # The detector's heuristic remediation text stays put — additive, not replaced.
    assert issue.remediation == "Review and fix the identified issue"

    # osoji#168: the description-family finding is triaged like everything
    # else — a verdict lands instead of the old silent pass-through.
    block = next(i for i in debris_issues if "commented-out" in i.message)
    assert block.verdict == "confirmed"
    assert block.confidence == 0.7
    assert block.finding_id

    # Every kept debris finding carried a verdict → the untriaged floor is 0.
    assert result.scorecard is not None
    assert result.scorecard.debris_untriaged == 0


def test_untriaged_pass_through_is_counted_and_marked_end_to_end(temp_dir):
    """The osoji#168 interim floor: a kept debris finding that never received a
    verdict (here: a needle-less dead_code whose require_any gate was unmet)
    is counted on the scorecard and tagged [untriaged] in the report."""
    from osoji.audit import format_audit_report

    _write(temp_dir, "src/x.py",
           "def old_helper():\n    pass\n\n\n# unattributed block\npass\n")
    _write_findings(temp_dir, "src/x.py", [
        {
            "category": "dead_code", "line_start": 1, "line_end": 2,
            "severity": "warning", "description": "`old_helper` is defined but never used",
        },
        {
            # No backticked/PascalCase needles → no cross_file_reference
            # evidence gatherable → pass-through, kept unverified.
            "category": "dead_code", "line_start": 5, "line_end": 6,
            "severity": "warning", "description": "unused block of code",
        },
    ])
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = FakeProvider(_verdicts_result([
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "dead"},
    ]))

    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, exclude={"shadow", "doc-analysis"},
        ))

    assert result.scorecard is not None
    assert result.scorecard.debris_untriaged == 1

    report = format_audit_report(result)
    assert "[untriaged]" in report
    assert "Untriaged debris" in report


def test_untriaged_floor_is_none_when_debris_phase_excluded(temp_dir):
    """None (not 0) when the debris phase didn't run — an excluded phase must
    not read as a clean bill of health."""
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = FakeProvider(_verdicts_result([]))

    with patch("osoji.facts.FactsDB", return_value=FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, exclude={"shadow", "doc-analysis", "debris"},
        ))

    assert result.scorecard is not None
    assert result.scorecard.debris_untriaged is None
