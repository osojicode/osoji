"""End-to-end tests for observable audit degradation (Track 2 PR-A, work#66 series).

The audit orchestrator wraps three best-effort Triage/manifest seams in
``except Exception`` (debris-triage, obligations-triage, manifest-write); a
fourth seam (doc-triage) already prints a warning. None of these previously
recorded anything — a failure there silently degraded the audit to "keep
everything unverified" with no trace. These tests run the real
``run_audit_async`` orchestration (mold of ``test_audit_incremental.py``) and
check the full chain: the failing seam is recorded in
``config.audit_degradations``, threaded onto ``Scorecard.degraded_phases``,
and rendered into the markdown report — without changing the underlying
best-effort behavior (findings are still kept, the audit still completes).
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from osoji.audit import format_audit_report, run_audit_async
from osoji.config import Config
from osoji.hasher import compute_file_hash, compute_impl_hash
from osoji.llm.types import CompletionResult, ToolCall

# --- environment helpers (mold of test_audit_incremental.py) ------------------


def _write(temp_dir: Path, rel: str, text: str) -> None:
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_facts(temp_dir: Path, source: str, string_literals: list[dict]) -> None:
    facts_file = temp_dir / ".osoji" / "facts" / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    facts_file.write_text(json.dumps({
        "source": source,
        "source_hash": "abc123",
        "imports": [],
        "exports": [],
        "calls": [],
        "string_literals": string_literals,
    }), encoding="utf-8")


def _one_implicit_contract_env(temp_dir: Path) -> None:
    _write(temp_dir, "src/producer.py", "def emit():\n    return 'my_category'\n")
    _write(temp_dir, "src/consumer.py", "def handle(x):\n    return x == 'my_category'\n")
    _write_facts(temp_dir, "src/producer.py", [
        {"value": "my_category", "context": "appended to list", "line": 2,
         "kind": "identifier", "usage": "produced"},
    ])
    _write_facts(temp_dir, "src/consumer.py", [
        {"value": "my_category", "context": "membership check", "line": 2,
         "kind": "identifier", "usage": "checked"},
    ])


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


def _debris_env(temp_dir: Path) -> None:
    _write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    _write_findings(temp_dir, "src/x.py", [{
        "category": "dead_code",
        "line_start": 1,
        "line_end": 2,
        "severity": "warning",
        "description": "`old_helper` is defined but never used",
    }])


class _FakeFacts:
    """FactsDB stand-in: every symbol has one stable cross-file reference (debris eligibility)."""

    def cross_file_references(self, symbol, source_path):
        return [{"file": "src/y.py", "kind": "import", "context": "uses it",
                 "resolves_to_source": True}]


class FakeProvider:
    """Canned submit_triage_verdicts provider; can raise instead (mold of
    test_audit_incremental.FakeProvider)."""

    def __init__(self, verdicts=None, error=None):
        self.calls = 0
        self._verdicts = verdicts
        self._error = error

    async def complete(self, messages, system, options):
        self.calls += 1
        if self._error is not None:
            raise self._error
        verdicts = self._verdicts
        if verdicts is None:
            validator = options.tool_input_validators[0]
            n = len(validator("submit_triage_verdicts", {"verdicts": []}))
            verdicts = [
                {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                 "reasoning": "genuine"}
                for i in range(n)
            ]
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{self.calls}", name="submit_triage_verdicts",
                input={"verdicts": verdicts},
            )],
            input_tokens=140, output_tokens=70,
            model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


_OBLIGATIONS_EXCLUDE = {"shadow", "doc-analysis", "debris"}


# --- Phase 3: debris-triage failure --------------------------------------------


def test_debris_triage_failure_surfaces_in_scorecard_and_report(temp_dir):
    # decide_junk_claims retries/bisects and swallows a per-chunk provider
    # failure internally (findings come back undecided rather than raising —
    # see junk_triage.py), so a canned erroring provider never reaches the
    # seam's own except. Failing one step earlier, obtaining the runtime,
    # exercises it directly.
    _debris_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)

    with patch("osoji.facts.FactsDB", return_value=_FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", side_effect=RuntimeError("boom")):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, exclude={"shadow", "doc-analysis"},
        ))

    # Best-effort: the debris finding is still kept (unverified), not dropped.
    debris_issues = [i for i in result.issues if i.exclude_key == "debris"]
    assert len(debris_issues) == 1

    assert config.audit_degradations == [{"phase": "debris-triage", "error": "boom"}]
    assert result.scorecard.degraded_phases == ["debris-triage"]

    report = format_audit_report(result)
    assert "Triage degradation" in report
    assert "debris-triage" in report


# --- Phase 3.5: obligations-triage failure -------------------------------------


def test_obligations_triage_failure_surfaces_in_scorecard_and_report(temp_dir):
    # Same rationale as the debris-triage test above: fail create_runtime
    # itself rather than the provider's complete(), since decide_junk_claims
    # absorbs a per-chunk provider failure without raising.
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)

    with patch("osoji.audit.create_runtime", side_effect=RuntimeError("boom")):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
        ))

    # Best-effort: the heuristic obligation finding is still kept, unverified.
    obligation_issues = [i for i in result.issues if i.exclude_key == "obligations"]
    assert len(obligation_issues) == 1

    assert config.audit_degradations == [{"phase": "obligations-triage", "error": "boom"}]
    assert result.scorecard.degraded_phases == ["obligations-triage"]

    report = format_audit_report(result)
    assert "Triage degradation" in report
    assert "obligations-triage" in report


# --- no degradation: the baseline stays clean ----------------------------------


def test_no_degradation_run_reports_none(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = FakeProvider()  # succeeds

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
        ))

    assert config.audit_degradations == []
    assert result.scorecard.degraded_phases is None

    report = format_audit_report(result)
    assert "Triage degradation" in report
    assert "none" in report


# --- V1-9 manifest-write failure ------------------------------------------------


def test_manifest_write_failure_recorded_without_failing_audit(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = FakeProvider()  # obligations triage succeeds; only the manifest write fails

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())), \
         patch("osoji.audit.write_manifest", side_effect=RuntimeError("disk full")):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
        ))

    # The manifest is an optimization; its failure must not fail the audit.
    assert result is not None
    assert config.audit_degradations == [{"phase": "manifest-write", "error": "disk full"}]
