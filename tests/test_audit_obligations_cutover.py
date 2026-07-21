"""Cutover gate for V1-5c: obligations on the unified Triage pipeline (work#30).

Unlike the other detector migrations, Phase 3.5 *gains* an LLM stage where none
existed: the heuristic StringContractChecker proposes contract findings, the
Claim Builder assembles the file-tuple context, and unified Triage decides each
claim. A canned ``FakeProvider`` stands in for the LLM (mold of
``test_audit_debris_cutover.py`` / ``test_junk_reachability_cutover.py``); the
assertions pin the migration's behavior:

- dismissed verdict -> the finding is suppressed;
- confirmed verdict -> kept, with the string-contract ``contract_class`` threaded
  onto the persisted finding;
- ``other``-class verdicts are counted for the CE-gap rate;
- provider failure keeps every finding unverified (best-effort);
- the claim call uses the unified ``TRIAGE_SYSTEM_PROMPT`` (identity pin).
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from osoji.audit import _run_phase3_5_async, run_audit_async
from osoji.config import Config
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import TRIAGE_SYSTEM_PROMPT


# --- environment helpers ------------------------------------------------------


def _write(temp_dir: Path, rel: str, text: str) -> None:
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_facts(temp_dir: Path, source: str, string_literals: list[dict], **extra) -> None:
    facts_file = temp_dir / ".osoji" / "facts" / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    facts_file.write_text(json.dumps({
        "source": source,
        "source_hash": "abc123",
        "imports": [],
        "exports": [],
        "calls": [],
        "string_literals": string_literals,
        **extra,
    }), encoding="utf-8")


def _one_implicit_contract_env(temp_dir: Path) -> None:
    """A producer/consumer pair yielding exactly one implicit_contract finding.

    Real source files make the reference-sweep corpus non-empty, so the built
    claim is evidence-sufficient and routes to the claim-mode LLM call.
    """
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


def _three_pair_cluster_env(temp_dir: Path) -> None:
    """One literal, fragile across three producer/consumer pairs.

    Detection proposes three per-pair findings; the V1-5c clustering pass
    collapses them to a single canonical contract, so exactly ONE claim reaches
    Triage and its verdict governs all three sites.
    """
    _write(temp_dir, "src/prod.py", "def emit():\n    return 'shared_kind'\n")
    _write_facts(temp_dir, "src/prod.py", [
        {"value": "shared_kind", "context": "returned", "line": 2,
         "kind": "identifier", "usage": "produced"},
    ])
    for i in (1, 2, 3):
        _write(temp_dir, f"src/cons{i}.py", f"def h{i}(x):\n    return x == 'shared_kind'\n")
        _write_facts(temp_dir, f"src/cons{i}.py", [
            {"value": "shared_kind", "context": "membership check", "line": 2,
             "kind": "identifier", "usage": "checked"},
        ])


def _two_distinct_contracts_env(temp_dir: Path) -> None:
    """Two distinct literals produced by one hub file, checked in two consumers.

    They share the producer file but are two distinct contracts -> two claims.
    """
    _write(temp_dir, "src/hub.py", "def emit():\n    return ('alpha_kind', 'beta_kind')\n")
    _write(temp_dir, "src/cons_a.py", "def a(x):\n    return x == 'alpha_kind'\n")
    _write(temp_dir, "src/cons_b.py", "def b(x):\n    return x == 'beta_kind'\n")
    _write_facts(temp_dir, "src/hub.py", [
        {"value": "alpha_kind", "context": "returned", "line": 2,
         "kind": "identifier", "usage": "produced"},
        {"value": "beta_kind", "context": "returned", "line": 2,
         "kind": "identifier", "usage": "produced"},
    ])
    _write_facts(temp_dir, "src/cons_a.py", [
        {"value": "alpha_kind", "context": "membership check", "line": 2,
         "kind": "identifier", "usage": "checked"},
    ])
    _write_facts(temp_dir, "src/cons_b.py", [
        {"value": "beta_kind", "context": "membership check", "line": 2,
         "kind": "identifier", "usage": "checked"},
    ])


class FakeProvider:
    """Canned submit_triage_verdicts provider; records the system prompt."""

    def __init__(self, verdicts=None, error=None):
        self.calls = 0
        self.last_system = None
        self._verdicts = verdicts
        self._error = error

    async def complete(self, messages, system, options):
        self.calls += 1
        self.last_system = system
        if self._error is not None:
            raise self._error
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{self.calls}", name="submit_triage_verdicts",
                input={"verdicts": self._verdicts or []},
            )],
            input_tokens=140, output_tokens=70,
            model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


def _run(temp_dir, provider):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        return asyncio.run(_run_phase3_5_async(config, True, MagicMock(), False))


# --- tests --------------------------------------------------------------------


def test_disabled_returns_empty_tuple(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = asyncio.run(_run_phase3_5_async(config, False, MagicMock(), False))
    assert result == ([], (0, 0), 0, 0)


def test_dismissed_verdict_suppresses(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9,
         "reasoning": "coincidental", "contract_class": "coincidence"},
    ])

    findings, tokens, triaged, other = _run(temp_dir, provider)

    assert provider.calls == 1
    assert findings == []                 # dismissed -> suppressed
    assert tokens == (140, 70)
    assert triaged == 1
    assert other == 0


def test_confirmed_verdict_kept_with_contract_class(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.8,
         "reasoning": "two sites share a bare literal", "contract_class": "unnamed_obligation"},
    ])

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    assert len(findings) == 1
    assert findings[0].finding_type == "implicit_contract"
    assert findings[0].contract_class == "unnamed_obligation"
    assert triaged == 1
    assert other == 0


def test_confirmed_verdict_carries_triage_outputs_additively(temp_dir):
    """The Triage outputs (verdict/confidence/reasoning/suggested_fix/id) ride
    along additively; the heuristic severity/remediation/confidence are
    untouched (still governed by the silent-value/loud-name rationale)."""
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.8,
         "reasoning": "two sites share a bare literal", "contract_class": "unnamed_obligation",
         "suggested_fix": "extract a shared constant"},
    ])

    findings, _tokens, _triaged, _other = _run(temp_dir, provider)
    f = findings[0]

    assert f.verdict == "confirmed"
    assert f.triage_confidence == 0.8
    assert f.triage_reasoning == "two sites share a bare literal"
    assert f.suggested_fix == "extract a shared constant"
    assert f.finding_id
    # heuristic fields are unchanged by the overlay (still whatever the
    # heuristic StringContractChecker proposed, not re-scaled by Triage)
    assert f.severity == "info"       # heuristic implicit_contract severity
    assert f.confidence == 0.5        # heuristic confidence, untouched by 0.8 above
    assert f.remediation              # heuristic remediation text, untouched


def test_triage_outputs_land_on_the_audit_issue_end_to_end(temp_dir):
    """End-to-end (run_audit_async): the ContractFinding's Triage outputs reach
    the product-boundary AuditIssue, while severity/remediation stay heuristic."""
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.8,
         "reasoning": "two sites share a bare literal", "contract_class": "unnamed_obligation",
         "suggested_fix": "extract a shared constant"},
    ])
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, obligations=True,
            exclude={"shadow", "doc-analysis", "debris"},
        ))

    obligation_issues = [i for i in result.issues if i.exclude_key == "obligations"]
    assert len(obligation_issues) == 1
    issue = obligation_issues[0]
    assert issue.verdict == "confirmed"
    assert issue.confidence == 0.8
    assert issue.triage_reasoning == "two sites share a bare literal"
    assert issue.suggested_fix == "extract a shared constant"
    assert issue.contract_class == "unnamed_obligation"
    assert issue.finding_id
    # severity/remediation stay heuristic — Triage does not re-grade obligations.
    assert issue.severity == "info"


def test_other_class_counts_toward_ce_gap(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.5,
         "reasoning": "outside the taxonomy", "contract_class": "other"},
    ])

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    assert len(findings) == 1
    assert findings[0].contract_class == "other"
    assert (triaged, other) == (1, 1)


def test_provider_failure_keeps_findings_unverified(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(error=RuntimeError("boom"))

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    # Best-effort: the heuristic finding survives, unverified — no class was
    # recorded and it was not counted as triaged.
    assert len(findings) == 1
    assert findings[0].finding_type == "implicit_contract"
    assert findings[0].contract_class is None
    assert (triaged, other) == (0, 0)


def test_provider_failure_records_obligations_triage_degradation(temp_dir):
    """A Triage-seam failure keeps findings AND is recorded.

    Mirrors the debris-triage seam's degradation contract. ``decide_junk_claims``
    swallows a per-chunk provider failure internally (see
    test_audit_debris_cutover.py's equivalent test for why), so the seam's own
    ``except Exception`` at the ``_run_phase3_5_async`` level is exercised by
    failing one step earlier: obtaining the runtime itself.
    """
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False)
    config.audit_degradations = []

    with patch("osoji.audit.create_runtime", side_effect=RuntimeError("boom")):
        findings, _tokens, triaged, other = asyncio.run(
            _run_phase3_5_async(config, True, MagicMock(), False)
        )

    assert len(findings) == 1  # best-effort: kept, unverified
    assert (triaged, other) == (0, 0)
    assert config.audit_degradations == [{"phase": "obligations-triage", "error": "boom"}]


def test_claim_call_uses_unified_triage_prompt(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 1.0,
         "reasoning": "real", "contract_class": "named_obligation"},
    ])

    _run(temp_dir, provider)

    # Identity pin: the shared unified rubric, not a per-detector or debris prompt.
    assert provider.last_system is TRIAGE_SYSTEM_PROMPT


# --- V1-5c deeper fix: contract-level dedup with representative guarantee ------


def test_cluster_confirmed_ships_one_finding_naming_all_pairs(temp_dir):
    """Three per-pair findings of one contract -> one claim; confirming it ships
    a single finding that names every binding site."""
    _three_pair_cluster_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.8,
         "reasoning": "one literal binds three sites", "contract_class": "unnamed_obligation"},
    ])

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    assert provider.calls == 1
    assert triaged == 1                       # one claim represented the whole cluster
    assert len(findings) == 1
    f = findings[0]
    assert f.contract_class == "unnamed_obligation"
    assert f.evidence["site_count"] == 3
    assert "3 sites" in f.description


def test_cluster_dismissed_drops_the_whole_cluster(temp_dir):
    """A single dismissal on the canonical claim drops all three sites — the
    representative guarantee's converse."""
    _three_pair_cluster_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9,
         "reasoning": "coincidental", "contract_class": "coincidence"},
    ])

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    assert triaged == 1
    assert findings == []                     # nothing survives the cluster's verdict


def test_two_distinct_contracts_sharing_a_file_make_two_claims(temp_dir):
    """Two distinct literals from one hub file -> two claims, not merged by the
    shared file; confirming both ships two findings."""
    _two_distinct_contracts_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.7,
         "reasoning": "alpha", "contract_class": "unnamed_obligation"},
        {"batch_index": 1, "verdict": "confirmed", "confidence": 0.7,
         "reasoning": "beta", "contract_class": "unnamed_obligation"},
    ])

    findings, _tokens, triaged, other = _run(temp_dir, provider)

    assert triaged == 2                        # two distinct claims despite the shared file
    assert len(findings) == 2
    assert {f.value for f in findings} == {"alpha_kind", "beta_kind"}
