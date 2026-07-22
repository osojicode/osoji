"""End-to-end tests for billing/credit fail-fast serialization (issue #160).

When the provider dies mid-audit with a permanent billing/credit error, the
run must not discard all completed analysis. The circuit breaker trips on the
first permanent error, the terminal serialization path still runs (so
``audit-result.json`` exists and ``osoji report`` works), the affected phase is
named in ``degraded_phases``, and the run exits nonzero with a message naming
the billing cause instead of crashing with an unhandled SDK error.

Molded on ``test_audit_degradation.py`` (real ``run_audit_async`` orchestration
with a canned provider injected through ``osoji.audit.create_runtime``).
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from osoji.audit import run_audit_async
from osoji.config import Config
from osoji.llm.types import CompletionResult, ProviderPermanentError, ToolCall


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


class _BillingError(Exception):
    """Stand-in for anthropic's billing 400 (credit balance too low)."""

    def __init__(self) -> None:
        super().__init__(
            "Error code: 400 - Your credit balance is too low to access the "
            "Anthropic API."
        )
        self.status_code = 400
        self.message = str(self)


class _BillingProvider:
    """Raises a raw billing-class SDK error on every completion."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, system, options):
        self.calls += 1
        raise _BillingError()

    async def close(self):
        pass


class _OkProvider:
    """Succeeds — used to prove the clean path is untouched."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, system, options):
        self.calls += 1
        validator = options.tool_input_validators[0]
        n = len(validator("submit_triage_verdicts", {"verdicts": []}))
        verdicts = [
            {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
             "reasoning": "genuine"}
            for i in range(n)
        ]
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(id=f"tc{self.calls}", name="submit_triage_verdicts",
                                 input={"verdicts": verdicts})],
            input_tokens=100, output_tokens=50, model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


_OBLIGATIONS_EXCLUDE = {"shadow", "doc-analysis", "debris"}


def test_billing_error_serializes_result_and_exits_nonzero(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = _BillingProvider()

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        with pytest.raises(ProviderPermanentError) as exc_info:
            asyncio.run(run_audit_async(
                config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
            ))

    # The run exits nonzero with a message naming the billing cause.
    assert exc_info.value.reason == "billing"
    assert "billing" in str(exc_info.value).lower()

    # The terminal serialization path ran even though a phase hit the error.
    result_path = temp_dir / ".osoji" / "analysis" / "audit-result.json"
    assert result_path.exists()
    scorecard_path = temp_dir / ".osoji" / "analysis" / "scorecard.json"
    assert scorecard_path.exists()
    ledger_path = temp_dir / ".osoji" / "analysis" / "decided-findings.json"
    assert ledger_path.exists()

    # The affected phase is named in degraded_phases (persisted to disk).
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert scorecard["degraded_phases"] is not None
    assert "obligations-triage" in scorecard["degraded_phases"]

    # config records the degradation for the same phase.
    phases = {d["phase"] for d in config.audit_degradations}
    assert "obligations-triage" in phases

    # The heuristic obligation finding is preserved in the serialized result
    # (kept unverified, not discarded).
    audit_result = json.loads(result_path.read_text(encoding="utf-8"))
    obligation_issues = [
        i for i in audit_result["issues"] if i.get("exclude_key") == "obligations"
    ]
    assert len(obligation_issues) == 1


def test_breaker_trips_and_short_circuits_within_phase(temp_dir):
    # Two independent contracts -> two claims. The first triage call trips the
    # breaker; the circuit stays open, so the provider is not called once per
    # claim indefinitely. (Best-effort: findings are kept, run still serializes.)
    _write(temp_dir, "src/producer.py",
           "def emit():\n    return 'cat_a'\n\ndef emit2():\n    return 'cat_b'\n")
    _write(temp_dir, "src/consumer.py",
           "def handle(x):\n    return x == 'cat_a'\n\ndef h2(y):\n    return y == 'cat_b'\n")
    _write_facts(temp_dir, "src/producer.py", [
        {"value": "cat_a", "context": "appended", "line": 2, "kind": "identifier", "usage": "produced"},
        {"value": "cat_b", "context": "appended", "line": 5, "kind": "identifier", "usage": "produced"},
    ])
    _write_facts(temp_dir, "src/consumer.py", [
        {"value": "cat_a", "context": "membership", "line": 2, "kind": "identifier", "usage": "checked"},
        {"value": "cat_b", "context": "membership", "line": 5, "kind": "identifier", "usage": "checked"},
    ])
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = _BillingProvider()

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        with pytest.raises(ProviderPermanentError):
            asyncio.run(run_audit_async(
                config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
            ))

    breaker = config.provider_circuit_breaker
    assert breaker.tripped
    # audit-result.json still written despite the mid-run failure.
    assert (temp_dir / ".osoji" / "analysis" / "audit-result.json").exists()


def test_clean_run_never_trips_breaker(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    provider = _OkProvider()

    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config, fix_shadow=False, obligations=True, exclude=_OBLIGATIONS_EXCLUDE,
        ))

    assert not config.provider_circuit_breaker.tripped
    assert config.audit_degradations == []
    assert result.scorecard.degraded_phases is None
