"""Cutover gate for V1-5a: deadcode/deadparam on the unified Triage pipeline.

Mock-equivalence tests in the ``test_audit_debris_cutover.py`` mold: a canned
provider stands in for the LLM, and the assertions pin the behavior the
migration must preserve or deliberately change (osojicode/work#28):

- confirmed -> reported; dismissed / uncertain / undecided -> dropped
  (candidates are hypotheses; the polarity is inverted vs debris suppression).
- AST-proven candidates with a clean repo sweep are confirmed mechanically —
  ZERO provider calls, ``confidence_source="ast_proven"`` preserved.
- An AST-proven candidate whose sweep hits the symbol name inside a quoted
  string is demoted to Triage, and the rendered claim carries the positional
  ``[match is inside a quoted string]`` marker (the dead_symbol-001 residual).
- Prompt identity: the unified ``TRIAGE_SYSTEM_PROMPT`` — not the deleted
  per-detector prompts, not the retired legacy debris prompt.
- Chunking: >12 claims split across calls; a failing chunk bisects once, then
  keeps its claims undecided rather than crashing the run.
"""

import json

import pytest

from osoji.config import Config
from osoji.deadcode import DeadCodeAnalyzer
from osoji.evidence_builders import BuildContext
from osoji.findings_adapter import finding_from_dead_code_candidate
from osoji.junk_triage import build_junk_claims, decide_junk_claims
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import TRIAGE_SYSTEM_PROMPT


# --- environment helpers ------------------------------------------------------


def _write(temp_dir, rel, text):
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_symbols(temp_dir, source, symbols):
    _write(
        temp_dir,
        f".osoji/symbols/{source}.symbols.json",
        json.dumps({
            "source": source,
            "source_hash": "abc",
            "file_role": "service",
            "symbols": symbols,
        }),
    )


def _write_facts(temp_dir, source, extraction_method="ast", imports=None, exports=None):
    safe = source.replace("/", "__")
    _write(
        temp_dir,
        f".osoji/facts/{safe}.facts.json",
        json.dumps({
            "source": source,
            "source_hash": "abc",
            "extraction_method": extraction_method,
            "imports": imports or [],
            "exports": exports or [],
            "calls": [],
            "member_writes": [],
            "string_literals": [],
        }),
    )


class FakeProvider:
    """Canned submit_triage_verdicts provider; records calls and prompts."""

    def __init__(self, verdicts_per_call=None, error=None):
        self.calls = 0
        self.last_system = None
        self.last_user = None
        self.batch_sizes = []
        self._verdicts_per_call = verdicts_per_call
        self._error = error

    async def complete(self, messages, system, options):
        self.calls += 1
        self.last_system = system
        self.last_user = messages[0].content
        if self._error is not None:
            raise self._error
        validator = options.tool_input_validators[0]
        n = len(validator("submit_triage_verdicts", {"verdicts": []}))
        self.batch_sizes.append(n)
        if self._verdicts_per_call is not None:
            verdicts = self._verdicts_per_call.pop(0)
        else:
            verdicts = [
                {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                 "reasoning": "No references"}
                for i in range(n)
            ]
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{self.calls}", name="submit_triage_verdicts",
                input={"verdicts": verdicts},
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )


def _ast_dead_symbol_env(temp_dir):
    """lib.py with one exported, unreferenced symbol under full-AST facts."""
    _write(temp_dir, "src/lib.py", "def dead_func():\n    return 1\n")
    _write_symbols(temp_dir, "src/lib.py", [
        {"name": "dead_func", "kind": "function", "line_start": 1,
         "line_end": 2, "visibility": "public"},
    ])
    _write_facts(temp_dir, "src/lib.py",
                 exports=[{"name": "dead_func", "kind": "function"}])


# --- AST fast path: mechanical confirm vs demotion ----------------------------


@pytest.mark.asyncio
async def test_ast_clean_zero_confirms_without_llm(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _ast_dead_symbol_env(temp_dir)
    provider = FakeProvider()

    result = await DeadCodeAnalyzer().analyze_async(provider, config)

    assert provider.calls == 0
    assert [f.name for f in result.findings] == ["dead_func"]
    assert result.findings[0].confidence_source == "ast_proven"
    assert result.findings[0].confidence == 1.0


@pytest.mark.asyncio
async def test_ast_string_literal_hit_demotes_to_triage(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _ast_dead_symbol_env(temp_dir)
    # No import edge (AST graph is clean) but the exact name appears as a
    # quoted dispatch key — the sweep must catch what the graph cannot.
    _write(temp_dir, "src/registry.py",
           'handler = getattr(lib, "dead_func")\n')
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9,
         "reasoning": "Reachable via getattr string dispatch"},
    ]])

    result = await DeadCodeAnalyzer().analyze_async(provider, config)

    assert provider.calls == 1
    assert result.findings == []  # dismissed -> dropped
    # The rendered claim carried the positional dynamic-dispatch marker
    assert "[match is inside a quoted string]" in provider.last_user


@pytest.mark.asyncio
async def test_unified_rubric_prompt_identity(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    # Grep-path candidate: non-AST facts force the LLM route
    _write(temp_dir, "src/lib.py", "def dead_func():\n    return 1\n")
    _write(temp_dir, "src/other.py", "print('unrelated')\n")
    _write_symbols(temp_dir, "src/lib.py", [
        {"name": "dead_func", "kind": "function", "line_start": 1,
         "line_end": 2, "visibility": "public"},
    ])
    _write_facts(temp_dir, "src/lib.py", extraction_method="llm",
                 exports=[{"name": "dead_func", "kind": "function"}])
    provider = FakeProvider()

    result = await DeadCodeAnalyzer().analyze_async(provider, config)

    assert provider.calls == 1
    assert provider.last_system == TRIAGE_SYSTEM_PROMPT
    assert [f.name for f in result.findings] == ["dead_func"]
    assert result.findings[0].confidence_source == "llm_inferred"


@pytest.mark.asyncio
async def test_uncertain_and_dismissed_are_dropped(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/lib.py",
           "def func_a():\n    return 1\n\ndef func_b():\n    return 2\n")
    _write(temp_dir, "src/other.py", "print('unrelated')\n")
    _write_symbols(temp_dir, "src/lib.py", [
        {"name": "func_a", "kind": "function", "line_start": 1,
         "line_end": 2, "visibility": "public"},
        {"name": "func_b", "kind": "function", "line_start": 4,
         "line_end": 5, "visibility": "public"},
    ])
    _write_facts(temp_dir, "src/lib.py", extraction_method="llm",
                 exports=[{"name": "func_a"}, {"name": "func_b"}])
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "uncertain", "confidence": 0.4,
         "reasoning": "Cannot decide"},
        {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8,
         "reasoning": "Framework dispatch"},
    ]])

    result = await DeadCodeAnalyzer().analyze_async(provider, config)

    assert result.findings == []
    assert result.total_candidates == 2


# --- decide_junk_claims: chunking and failure handling -------------------------


def _trivial_claims(config, n):
    from osoji.deadcode import DeadCodeCandidate

    findings = [
        finding_from_dead_code_candidate(DeadCodeCandidate(
            source_path=f"src/mod_{i}.py", name=f"sym_{i}", kind="function",
            line_start=1, line_end=2, ref_count=0,
        ))
        for i in range(n)
    ]
    ctx = BuildContext(config, facts_db=None, symbols_by_file={})
    # Empty corpus is fine here — these tests exercise the decide loop only.
    return build_junk_claims(findings, ctx)


@pytest.mark.asyncio
async def test_claims_split_into_bounded_chunks(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 13)
    provider = FakeProvider()

    decided, _in_tok, _out_tok = await decide_junk_claims(claims, config, provider)

    assert provider.batch_sizes == [12, 1]
    assert len(decided) == 13
    assert all(f.verdict == "confirmed" for f in decided)


@pytest.mark.asyncio
async def test_failing_chunk_bisects_then_keeps_claims_undecided(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 4)
    provider = FakeProvider(error=RuntimeError("boom"))

    decided, in_tok, out_tok = await decide_junk_claims(claims, config, provider)

    # 1 full-chunk attempt + 2 bisected halves, all failing
    assert provider.calls == 3
    assert len(decided) == 4
    assert all(f.verdict is None for f in decided)
    assert (in_tok, out_tok) == (0, 0)


@pytest.mark.asyncio
async def test_symbol_echo_mismatch_is_a_validation_error(temp_dir):
    """Cross-wired sibling verdicts are caught mechanically (A/B finding)."""
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 2)

    captured = {}

    class ProbingProvider(FakeProvider):
        async def complete(self, messages, system, options):
            validator = options.tool_input_validators[0]
            crossed = {"verdicts": [
                {"batch_index": 0, "symbol": claims[1].finding.symbol,
                 "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"},
                {"batch_index": 1, "symbol": claims[0].finding.symbol,
                 "verdict": "dismissed", "confidence": 0.9, "reasoning": "y"},
            ]}
            captured["crossed_errors"] = validator("submit_triage_verdicts", crossed)
            aligned = {"verdicts": [
                {"batch_index": 0, "symbol": claims[0].finding.symbol,
                 "verdict": "confirmed", "confidence": 0.9, "reasoning": "x"},
                {"batch_index": 1, "symbol": claims[1].finding.symbol,
                 "verdict": "dismissed", "confidence": 0.9, "reasoning": "y"},
            ]}
            captured["aligned_errors"] = validator("submit_triage_verdicts", aligned)
            return await super().complete(messages, system, options)

    provider = ProbingProvider()
    decided, _in_tok, _out_tok = await decide_junk_claims(claims, config, provider)

    assert len(captured["crossed_errors"]) == 2
    assert "re-check" in captured["crossed_errors"][0]
    assert captured["aligned_errors"] == []
    assert len(decided) == 2


# --- decide_junk_claims: verdict-cache session (V1-9) --------------------------


def _session_cache_for(claims):
    return {
        (c.finding.id, c.finding.evidence_fingerprint): {
            "verdict": "confirmed",
            "confidence": 0.9,
            "triage_reasoning": "cached",
            "suggested_fix": None,
            "severity": "warning",
            "contract_class": None,
        }
        for c in claims
    }


@pytest.mark.asyncio
async def test_session_cache_hits_skip_llm_and_are_counted(temp_dir):
    from osoji.audit_manifest import VerdictSession

    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 2)
    session = VerdictSession(cache=_session_cache_for(claims))
    config.verdict_session = session
    provider = FakeProvider(error=RuntimeError("LLM must not be called"))

    decided, in_tok, out_tok = await decide_junk_claims(claims, config, provider)

    assert provider.calls == 0
    assert all(f.verdict == "confirmed" for f in decided)
    assert all(f.triage_reasoning == "cached" for f in decided)
    assert session.claims_seen == 2
    assert session.cache_hits == 2
    assert session.hit_rate == 1.0
    assert (in_tok, out_tok) == (0, 0)


@pytest.mark.asyncio
async def test_session_harvests_fresh_verdicts(temp_dir):
    from osoji.audit_manifest import VerdictSession

    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 2)
    session = VerdictSession()
    config.verdict_session = session
    provider = FakeProvider()

    decided, _in_tok, _out_tok = await decide_junk_claims(claims, config, provider)

    assert provider.calls == 1
    assert session.claims_seen == 2
    assert session.cache_hits == 0
    assert set(session.harvested) == {c.finding.id for c in claims}
    entry = session.harvested[claims[0].finding.id]
    assert entry["verdict"] == "confirmed"
    assert entry["evidence_fingerprint"] == claims[0].finding.evidence_fingerprint
    assert entry["detector"] == "deadcode:dead_symbol"


@pytest.mark.asyncio
async def test_no_session_leaves_behavior_unchanged(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/anchor.py", "print('corpus is non-empty')\n")
    claims = _trivial_claims(config, 2)
    provider = FakeProvider()

    decided, _in_tok, _out_tok = await decide_junk_claims(claims, config, provider)

    assert provider.calls == 1
    assert all(f.verdict == "confirmed" for f in decided)
