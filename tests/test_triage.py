"""Tests for the unified Triage stage (V1-3).

Covers claim mode (this file's first section), exploration mode, the verdict
cache short-circuit, and insufficient-evidence escalation. All LLM calls use a
mock provider — no network, deterministic.
"""

from dataclasses import replace

import pytest

from osoji.config import Config
from osoji.evidence import Evidence
from osoji.findings import Finding
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import (
    Claim,
    Triage,
    TriageBatchResult,
    _apply_verdict,
    _render_evidence,
)


# --- helpers ---------------------------------------------------------------


@pytest.fixture
def config(temp_dir):
    return Config(root_path=temp_dir, respect_gitignore=False)


def make_finding(**overrides) -> Finding:
    base = dict(
        detector="debris:dead_code",
        gap_type="reachability",
        path="src/x.py",
        line_start=10,
        line_end=12,
        symbol="old_helper",
        contract_source="code",
        contract_claim="old_helper is exported but unused",
        observed_behavior="no references in any indexed file",
    )
    base.update(overrides)
    return Finding(**base)


class FakeProvider:
    """Minimal async provider returning queued CompletionResults in order.

    Records every ``complete`` call so tests can assert it was (or was not) hit.
    """

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def complete(self, messages, system, options):
        self.calls.append({"messages": messages, "system": system, "options": options})
        return self._results.pop(0)

    async def close(self):
        pass


def verdicts_result(verdicts, *, in_tok=100, out_tok=40) -> CompletionResult:
    """A claim-mode batch result: one submit_triage_verdicts tool call."""
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id="tc1", name="submit_triage_verdicts", input={"verdicts": verdicts})],
        input_tokens=in_tok,
        output_tokens=out_tok,
        model="test",
        stop_reason="tool_use",
    )


# --- claim mode ------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_mode_fills_all_verdict_fields(config):
    claims = [Claim(make_finding(symbol="a")), Claim(make_finding(symbol="b"))]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9,
             "reasoning": "no live path", "suggested_fix": "remove it", "severity": "warning"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8,
             "reasoning": "used via dispatch"},
        ])
    ])
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch(claims, mode="claim")

    assert isinstance(result, TriageBatchResult)
    a, b = result.findings
    assert a.verdict == "confirmed"
    assert a.confidence == 0.9
    assert a.triage_reasoning == "no live path"
    assert a.suggested_fix == "remove it"
    assert a.severity == "warning"
    assert b.verdict == "dismissed"
    assert result.input_tokens == 100
    assert result.output_tokens == 40
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_claim_mode_maps_by_batch_index_not_finding_id(config):
    # Two symbol-less debris findings that collide on finding.id: same detector,
    # path, claim, lines, symbol=None. The batch index must disambiguate them.
    f = make_finding(symbol=None, line_start=5, line_end=5, contract_claim="dup claim")
    f2 = make_finding(symbol=None, line_start=5, line_end=5, contract_claim="dup claim")
    assert f.id == f2.id  # precondition: they really do collide

    claims = [Claim(f), Claim(f2)]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "dismissed", "confidence": 0.7, "reasoning": "first"},
            {"batch_index": 1, "verdict": "confirmed", "confidence": 0.7, "reasoning": "second"},
        ])
    ])
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch(claims, mode="claim")

    assert result.findings[0].verdict == "dismissed"
    assert result.findings[0].triage_reasoning == "first"
    assert result.findings[1].verdict == "confirmed"
    assert result.findings[1].triage_reasoning == "second"


@pytest.mark.asyncio
async def test_claim_mode_empty_batch_makes_no_call(config):
    provider = FakeProvider([])
    triage = Triage(config, provider=provider)
    result = await triage.decide_batch([], mode="claim")
    assert result.findings == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_claim_mode_renders_evidence_into_prompt(config):
    finding = make_finding(
        evidence=[Evidence(
            kind="cross_file_reference",
            payload={"references": [{"file": "src/y.py", "kind": "import",
                                     "context": "from x import old_helper", "resolves_to_source": True}]},
        )],
    )
    provider = FakeProvider([
        verdicts_result([{"batch_index": 0, "verdict": "dismissed", "confidence": 0.6, "reasoning": "ok"}])
    ])
    triage = Triage(config, provider=provider)

    await triage.decide_batch([Claim(finding)], mode="claim")

    user_msg = provider.calls[0]["messages"][0].content
    assert "src/y.py" in user_msg
    assert "old_helper" in user_msg


@pytest.mark.asyncio
async def test_claim_mode_uses_supplied_system_prompt(config):
    provider = FakeProvider([
        verdicts_result([{"batch_index": 0, "verdict": "confirmed", "confidence": 1.0, "reasoning": "x"}])
    ])
    triage = Triage(config, provider=provider)
    await triage.decide_batch([Claim(make_finding())], mode="claim", system_prompt="CUSTOM-RUBRIC")
    assert provider.calls[0]["system"] == "CUSTOM-RUBRIC"


# --- cross-wiring guard for symbol-less claims (work#57) --------------------


@pytest.mark.asyncio
async def test_symbolless_claim_renders_location_echo(config):
    # Debris claims routinely carry symbol=None; without a rendered identity
    # there is nothing for the verdict to echo and misalignment survives.
    finding = make_finding(symbol=None, path="src/x.py", line_start=10)
    provider = FakeProvider([
        verdicts_result([{"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "dead"}])
    ])
    triage = Triage(config, provider=provider)

    await triage.decide_batch([Claim(finding)], mode="claim")

    user_msg = provider.calls[0]["messages"][0].content
    assert "Symbol: `src/x.py:10`" in user_msg


@pytest.mark.asyncio
async def test_completeness_validator_catches_cross_wired_symbolless_claims(config):
    # The V1-5e A/B observed off-by-one verdicts surviving validation because
    # the symbol-echo guard has nothing to compare on symbol=None claims. The
    # path:line fallback echo must make cross-wiring a validation error.
    claims = [
        Claim(make_finding(symbol=None, path="src/a.py", line_start=3, line_end=3)),
        Claim(make_finding(symbol=None, path="src/b.py", line_start=7, line_end=7)),
    ]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "y"},
        ])
    ])
    triage = Triage(config, provider=provider)
    await triage.decide_batch(claims, mode="claim")
    validator = provider.calls[0]["options"].tool_input_validators[0]

    cross_wired = validator("submit_triage_verdicts", {"verdicts": [
        {"batch_index": 0, "symbol": "src/b.py:7", "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"},
        {"batch_index": 1, "symbol": "src/a.py:3", "verdict": "dismissed", "confidence": 0.8, "reasoning": "y"},
    ]})
    assert len(cross_wired) == 2

    aligned = validator("submit_triage_verdicts", {"verdicts": [
        {"batch_index": 0, "symbol": "src/a.py:3", "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"},
        {"batch_index": 1, "symbol": "src/b.py:7", "verdict": "dismissed", "confidence": 0.8, "reasoning": "y"},
    ]})
    assert aligned == []


# --- evidence rendering (V1-4 kinds) ----------------------------------------


def test_render_surrounding_code_evidence():
    ev = Evidence(
        kind="surrounding_code",
        payload={
            "file": "src/x.py", "line_start": 5, "line_end": 20,
            "snippet": "10: def old_helper():", "anchor": "symbol",
            "enclosing_symbol": {"name": "Outer", "kind": "class",
                                 "line_start": 1, "line_end": 40},
        },
    )
    out = _render_evidence(ev)
    assert not out.startswith("{")  # rendered, not the JSON-dump fallback
    assert "src/x.py" in out
    assert "def old_helper():" in out
    assert "Outer" in out


def test_render_declared_intent_evidence():
    ev = Evidence(
        kind="declared_intent",
        payload={"file": "src/x.py",
                 "blocks": [{"label": "preceding_lines", "line_start": 3,
                             "text": "# NOTE: legacy shim"}]},
    )
    out = _render_evidence(ev)
    assert not out.startswith("{")  # rendered, not the JSON-dump fallback
    assert "NOTE: legacy shim" in out
    assert "preceding" in out


def test_render_zero_hit_scan_scope_states_absence():
    # Evidence-of-absence must render as an explicit statement, not an empty list.
    ev = Evidence(
        kind="cross_file_reference",
        payload={"references": [], "shadow_excerpts": {},
                 "scan_scope": {"files_scanned": 312, "needles": ["old_helper"]}},
    )
    out = _render_evidence(ev)
    assert "No references" in out
    assert "312" in out
    assert "old_helper" in out


def test_render_export_surface():
    ev = Evidence(
        kind="cross_file_reference",
        payload={"references": [], "shadow_excerpts": {},
                 "scan_scope": {"files_scanned": 10, "needles": ["h"]},
                 "export_surface": {"symbol": "h", "exported_from_flagged_file": True}},
    )
    out = _render_evidence(ev)
    assert "export" in out.lower()


def test_render_shadow_doc_excerpt_payload():
    # V1-4 builder payload uses scope + excerpt (legacy 'content' still renders).
    ev = Evidence(
        kind="shadow_doc_claim",
        payload={"file": "src/x.py", "scope": "file", "excerpt": "Purpose: helpers."},
    )
    out = _render_evidence(ev)
    assert "Purpose: helpers." in out


# --- exploration mode ------------------------------------------------------


def tool_use_result(name, tool_input, *, call_id="t", in_tok=50, out_tok=20) -> CompletionResult:
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=name, input=tool_input)],
        input_tokens=in_tok,
        output_tokens=out_tok,
        model="test",
        stop_reason="tool_use",
    )


@pytest.fixture
def explore_repo(temp_dir):
    root = temp_dir / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "x.py").write_text("def old_helper():\n    return 'DISTINCTIVE-MARKER'\n", encoding="utf-8")
    return Config(root_path=root, respect_gitignore=False)


@pytest.mark.asyncio
async def test_exploration_runs_tools_then_applies_verdict(explore_repo):
    provider = FakeProvider([
        tool_use_result("read_file", {"path": "src/x.py"}, call_id="r1"),
        tool_use_result(
            "submit_triage_verdict",
            {"verdict": "dismissed", "confidence": 0.8, "reasoning": "found a use"},
            call_id="v1",
        ),
    ])
    triage = Triage(explore_repo, provider=provider)

    result = await triage.decide_batch([Claim(make_finding())], mode="exploration")

    assert result.findings[0].verdict == "dismissed"
    assert result.findings[0].triage_reasoning == "found a use"
    # trace records both tool calls in order
    names = [c["name"] for c in result.exploration_traces[0]["calls"]]
    assert names == ["read_file", "submit_triage_verdict"]
    # two provider turns, and the executor output was fed back as a tool_result
    assert len(provider.calls) == 2
    second_turn_msgs = provider.calls[1]["messages"]
    fed_back = "".join(
        block.get("content", "")
        for m in second_turn_msgs
        if isinstance(m.content, list)
        for block in m.content
        if block.get("type") == "tool_result"
    )
    assert "DISTINCTIVE-MARKER" in fed_back


@pytest.mark.asyncio
async def test_exploration_uses_auto_tool_choice(explore_repo):
    provider = FakeProvider([
        tool_use_result("submit_triage_verdict",
                        {"verdict": "confirmed", "confidence": 1.0, "reasoning": "dead"}, call_id="v1"),
    ])
    triage = Triage(explore_repo, provider=provider)
    await triage.decide_batch([Claim(make_finding())], mode="exploration")
    assert provider.calls[0]["options"].tool_choice == {"type": "auto"}


@pytest.mark.asyncio
async def test_exploration_turn_limit_yields_uncertain(explore_repo):
    # Model keeps reading, never submits a verdict → bounded to 'uncertain'.
    provider = FakeProvider([
        tool_use_result("read_file", {"path": "src/x.py"}, call_id=f"r{i}")
        for i in range(20)
    ])
    triage = Triage(explore_repo, provider=provider)

    result = await triage.decide_batch([Claim(make_finding())], mode="exploration")

    assert result.findings[0].verdict == "uncertain"
    assert len(provider.calls) == 8  # _MAX_EXPLORATION_TURNS


# --- verdict cache (V1-9 hook) ---------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_llm(config):
    finding = make_finding(evidence_fingerprint="fp-1")
    cache = {
        (finding.id, "fp-1"): {
            "verdict": "dismissed", "confidence": 0.95,
            "triage_reasoning": "cached: alive via dispatch",
            "suggested_fix": "", "severity": "info",
        }
    }
    provider = FakeProvider([])  # empty: any LLM call would IndexError
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch([Claim(finding)], mode="claim", verdict_cache=cache)

    assert provider.calls == []  # the LLM was never called
    assert result.findings[0].verdict == "dismissed"
    assert result.findings[0].triage_reasoning == "cached: alive via dispatch"
    assert result.verdict_cache_hit_rate == 1.0


@pytest.mark.asyncio
async def test_none_fingerprint_is_cache_ineligible(config):
    # Two findings collide on id; one cache entry keyed (id, None) must NOT be
    # reused — None fingerprint is always triaged.
    finding = make_finding(evidence_fingerprint=None)
    cache = {(finding.id, None): {"verdict": "dismissed", "confidence": 1.0}}
    provider = FakeProvider([
        verdicts_result([{"batch_index": 0, "verdict": "confirmed", "confidence": 0.5, "reasoning": "fresh"}])
    ])
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch([Claim(finding)], mode="claim", verdict_cache=cache)

    assert len(provider.calls) == 1  # triaged, not served from cache
    assert result.findings[0].verdict == "confirmed"
    assert result.verdict_cache_hit_rate == 0.0


# --- escalation routing (dormant in production) ----------------------------


@pytest.mark.asyncio
async def test_insufficient_evidence_passes_through_by_default(config):
    # decision 1: no-evidence claims stay kept-unverified; counted, not escalated.
    provider = FakeProvider([])  # must not be called
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch(
        [Claim(make_finding(), insufficient_evidence=True)], mode="claim"
    )

    assert provider.calls == []
    assert result.findings[0].verdict is None  # untouched / pass-through
    assert result.would_escalate_count == 1


@pytest.mark.asyncio
async def test_insufficient_evidence_escalates_when_enabled(explore_repo):
    provider = FakeProvider([
        tool_use_result("submit_triage_verdict",
                        {"verdict": "confirmed", "confidence": 0.9, "reasoning": "explored"}, call_id="v1"),
    ])
    triage = Triage(explore_repo, provider=provider)

    result = await triage.decide_batch(
        [Claim(make_finding(), insufficient_evidence=True)],
        mode="claim",
        escalate_insufficient=True,
    )

    assert result.findings[0].verdict == "confirmed"
    assert result.would_escalate_count == 1
    assert len(result.exploration_traces) == 1


# --- decided-findings ledger (osojicode/work#35) ----------------------------


@pytest.mark.asyncio
async def test_decide_batch_appends_decided_findings_to_ledger(config):
    config.decided_ledger = []
    claims = [Claim(make_finding(symbol="a")), Claim(make_finding(symbol="b"))]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "no live path"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "used via dispatch"},
        ])
    ])
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch(claims, mode="claim")

    assert len(config.decided_ledger) == 2
    ledger_by_symbol = {e["symbol"]: e for e in config.decided_ledger}
    assert ledger_by_symbol["a"]["verdict"] == "confirmed"
    assert ledger_by_symbol["a"]["id"] == result.findings[0].id
    assert ledger_by_symbol["b"]["verdict"] == "dismissed"


@pytest.mark.asyncio
async def test_decide_batch_without_ledger_attached_does_not_crash(config):
    # config.decided_ledger is not set here -- mirrors every other test in
    # this file, which calls decide_batch directly without the audit
    # orchestrator's attach (see audit.py's run_audit_async).
    assert not hasattr(config, "decided_ledger")
    claims = [Claim(make_finding(symbol="a"))]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "no live path"},
        ])
    ])
    triage = Triage(config, provider=provider)

    result = await triage.decide_batch(claims, mode="claim")

    assert result.findings[0].verdict == "confirmed"


# --- verdict/reasoning consistency guard (work#78) -------------------------


def test_confirmed_with_trailing_dismissal_reasoning_routes_to_uncertain():
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "confirmed",
        "confidence": 0.85,
        "reasoning": "The symbol has no live references. Dismissing on Reality.",
    })
    assert f.verdict == "uncertain"
    assert "Dismissing on Reality." in f.triage_reasoning
    assert "triage-guard" in f.triage_reasoning


def test_dismissed_with_trailing_confirm_reasoning_routes_to_uncertain():
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "dismissed",
        "confidence": 0.8,
        "reasoning": "Both predicates hold. Confirming on Reality and Actionability.",
    })
    assert f.verdict == "uncertain"
    assert "triage-guard" in f.triage_reasoning


def test_confirmed_with_negated_dismissal_language_is_untouched():
    reasoning = (
        "The cross-file hits are comments only; nothing justifies dismissing. "
        "Confirming on both predicates."
    )
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "confirmed",
        "confidence": 0.9,
        "reasoning": reasoning,
    })
    assert f.verdict == "confirmed"
    assert f.triage_reasoning == reasoning


def test_single_sentence_negated_dismissal_is_untouched():
    reasoning = "The evidence gives no ground for dismissing this gap."
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "confirmed",
        "confidence": 0.75,
        "reasoning": reasoning,
    })
    assert f.verdict == "confirmed"
    assert f.triage_reasoning == reasoning


def test_matching_verdict_and_reasoning_unchanged():
    confirmed = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "confirmed",
        "confidence": 0.9,
        "reasoning": "No live path reaches the symbol. Confirming on both predicates.",
    })
    assert confirmed.verdict == "confirmed"
    dismissed = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "dismissed",
        "confidence": 0.9,
        "reasoning": "The import at src/y.py:3 is a real use. Dismissing on Reality.",
    })
    assert dismissed.verdict == "dismissed"


def test_missing_reasoning_leaves_verdict_unchanged():
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "confirmed",
        "confidence": 0.9,
    })
    assert f.verdict == "confirmed"
    assert f.triage_reasoning is None


def test_uncertain_verdict_never_rewritten():
    f = _apply_verdict(make_finding(), {
        "batch_index": 0,
        "verdict": "uncertain",
        "confidence": 0.4,
        "reasoning": "Dismissing feels wrong but confirming lacks a path.",
    })
    assert f.verdict == "uncertain"
    assert "triage-guard" not in f.triage_reasoning


# --- malformed verdict shapes (observed in live replays) --------------------


@pytest.mark.asyncio
async def test_completeness_validator_rejects_malformed_verdict_shapes(config):
    # Live corpus replays observed models emitting the verdicts array
    # JSON-encoded as one string, or entries as bare strings; the validator
    # crashed (AttributeError) and the whole chunk's claims went undecided.
    # Malformed shape must be a validation error (re-ask), never an exception.
    claims = [Claim(make_finding(symbol="a"))]
    provider = FakeProvider([
        verdicts_result([{"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"}])
    ])
    triage = Triage(config, provider=provider)
    await triage.decide_batch(claims, mode="claim")
    validator = provider.calls[0]["options"].tool_input_validators[0]

    as_string = validator("submit_triage_verdicts", {"verdicts": '[{"batch_index": 0}]'})
    assert as_string and all(isinstance(e, str) for e in as_string)

    entry_string = validator("submit_triage_verdicts", {"verdicts": ["confirmed"]})
    assert entry_string and all(isinstance(e, str) for e in entry_string)

    non_list = validator("submit_triage_verdicts", {"verdicts": 42})
    assert non_list and all(isinstance(e, str) for e in non_list)


@pytest.mark.asyncio
async def test_malformed_verdict_entries_do_not_crash_the_batch(config):
    # Defense in depth for the parse loop: if a malformed entry survives
    # validation (provider without validator support), the batch must still
    # decide the well-formed entries and leave the malformed one undecided.
    claims = [Claim(make_finding(symbol="a")), Claim(make_finding(symbol="b"))]
    provider = FakeProvider([
        verdicts_result([
            "confirmed",
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "used via dispatch"},
        ])
    ])
    triage = Triage(config, provider=provider)
    result = await triage.decide_batch(claims, mode="claim")
    assert result.findings[0].verdict is None
    assert result.findings[1].verdict == "dismissed"
