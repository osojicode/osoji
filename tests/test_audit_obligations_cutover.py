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

from osoji.audit import _run_phase3_5_async
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


def test_claim_call_uses_unified_triage_prompt(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider(verdicts=[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 1.0,
         "reasoning": "real", "contract_class": "named_obligation"},
    ])

    _run(temp_dir, provider)

    # Identity pin: the shared unified rubric, not a per-detector or debris prompt.
    assert provider.last_system is TRIAGE_SYSTEM_PROMPT
