"""Cutover gate for V1-5d: doc_analysis on the unified Triage pipeline (work#31).

Mock-equivalence tests in the ``test_junk_reachability_cutover.py`` mold: a
canned provider stands in for the LLM, and the assertions pin the behavior the
migration must preserve or deliberately change.

- The private per-doc verify pass is replaced by one unified Triage post-pass.
  ``dismissed`` suppresses (the sole false-positive verdict); ``confirmed`` and
  ``uncertain`` are kept — ``uncertain`` downgraded to warning with the triage
  reasoning attached (controller decision, 2026-07-04); an undecided finding
  (LLM/chunk failure) is kept unverified.
- Prompt identity: the unified ``TRIAGE_SYSTEM_PROMPT`` — not the deleted
  per-doc verify prompt, not ``DEBRIS_TRIAGE_SYSTEM_PROMPT``.
- Smallest-sufficient shadow scope: a local-drift doc finding gets file-scope
  shadow evidence, not root; a cross-directory claim gets root scope.
- Reconciliation: the four doc categories are explicit ``CLAIM_BUILDER_SCHEMA``
  keys (unprefixed) that resolve to ``gap_type="description"``.
"""

from pathlib import Path

import pytest

from osoji.claim_builder import CLAIM_BUILDER_SCHEMA, build_claims, category_of
from osoji.config import Config
from osoji.doc_analysis import DocAnalysisResult, DocFinding, _triage_doc_findings
from osoji.evidence_builders import BuildContext
from osoji.findings_adapter import finding_from_doc, gap_type_for
from osoji.llm.types import CompletionResult, ToolCall
from osoji.triage import DEBRIS_TRIAGE_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT


# --- helpers ------------------------------------------------------------------


def _write(temp_dir, rel, text):
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeProvider:
    """Canned submit_triage_verdicts provider; records calls and prompts."""

    def __init__(self, verdicts_per_call=None, error=None):
        self.calls = 0
        self.last_system = None
        self.last_user = None
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
        if self._verdicts_per_call is not None:
            verdicts = self._verdicts_per_call.pop(0)
        else:
            verdicts = [
                {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                 "reasoning": "contradiction confirmed"}
                for i in range(n)
            ]
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{self.calls}", name="submit_triage_verdicts",
                input={"verdicts": verdicts},
            )],
            input_tokens=100, output_tokens=50, model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


def _doc_finding(**over):
    kw = dict(
        category="incorrect_content",
        severity="error",
        description="README says the flag is --foo but the code uses --bar",
        shadow_ref="src/cli.py",
        evidence="def main(): --bar",
        remediation="Update the README",
        search_terms=["--foo"],
    )
    kw.update(over)
    return DocFinding(**kw)


def _result_with(temp_dir, findings, path="README.md", classification="reference"):
    # The doc file must exist so SurroundingCodeBuilder can satisfy the
    # description entry's require_any gate and the claim is actually decided.
    _write(temp_dir, path, "# Project\nUse the --foo flag.\n" * 3)
    return DocAnalysisResult(
        path=Path(path),
        classification=classification,
        confidence=0.9,
        classification_reason="doc",
        matched_shadows=["src/cli.py"],
        findings=findings,
    )


# --- verdict routing ----------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_findings_ship(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [
        _doc_finding(description="claim A"),
        _doc_finding(description="claim B"),
    ])
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "real"},
        {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "fp"},
    ]])

    await _triage_doc_findings(provider, config, [result])

    assert provider.calls == 1
    assert [f.description for f in result.findings] == ["claim A"]
    assert result.findings[0].verdict == "confirmed"
    assert result.findings[0].confidence == 0.9


@pytest.mark.asyncio
async def test_dismissed_suppresses(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [_doc_finding()])
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "dismissed", "confidence": 0.9, "reasoning": "fp"},
    ]])

    await _triage_doc_findings(provider, config, [result])

    assert result.findings == []


@pytest.mark.asyncio
async def test_llm_failure_keeps_findings(temp_dir):
    """Per-chunk keep-on-failure: findings survive unverified (verdict None)."""
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [
        _doc_finding(description="a"), _doc_finding(description="b"),
    ])
    provider = FakeProvider(error=RuntimeError("boom"))

    await _triage_doc_findings(provider, config, [result])

    assert [f.description for f in result.findings] == ["a", "b"]
    assert all(f.verdict is None for f in result.findings)


@pytest.mark.asyncio
async def test_uncertain_kept_as_warning_with_reasoning(temp_dir):
    """Controller decision: keep uncertain, downgrade to warning, attach reasoning."""
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [_doc_finding(severity="error")])
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "uncertain", "confidence": 0.4,
         "reasoning": "shadow-doc omission is not project absence"},
    ]])

    await _triage_doc_findings(provider, config, [result])

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.verdict == "uncertain"
    assert f.severity == "warning"
    assert "omission" in (f.triage_reasoning or "")


@pytest.mark.asyncio
async def test_confirmed_verdict_can_regrade_severity(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [_doc_finding(severity="error")])
    provider = FakeProvider(verdicts_per_call=[[
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9,
         "reasoning": "partial", "severity": "warning"},
    ]])

    await _triage_doc_findings(provider, config, [result])

    assert result.findings[0].verdict == "confirmed"
    assert result.findings[0].severity == "warning"


@pytest.mark.asyncio
async def test_no_findings_makes_no_llm_call(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [])
    provider = FakeProvider()

    in_tok, out_tok = await _triage_doc_findings(provider, config, [result])

    assert provider.calls == 0
    assert (in_tok, out_tok) == (0, 0)


@pytest.mark.asyncio
async def test_debris_result_findings_are_not_triaged(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [_doc_finding()], classification="process_artifact")
    provider = FakeProvider()

    await _triage_doc_findings(provider, config, [result])

    assert provider.calls == 0
    assert len(result.findings) == 1  # untouched


@pytest.mark.asyncio
async def test_cutover_uses_unified_triage_prompt(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    result = _result_with(temp_dir, [_doc_finding()])
    provider = FakeProvider()

    await _triage_doc_findings(provider, config, [result])

    assert provider.calls == 1
    assert provider.last_system == TRIAGE_SYSTEM_PROMPT
    assert provider.last_system != DEBRIS_TRIAGE_SYSTEM_PROMPT
    assert "single verifier for every code-quality finding" in provider.last_system


# --- smallest-sufficient shadow scope -----------------------------------------


def _shadow_evidence(claim):
    return [e for e in claim.finding.evidence if e.kind == "shadow_doc_claim"]


def test_doc_finding_gets_file_scope_not_root(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/foo.py", "def hello():\n    return 1\n")
    _write(temp_dir, ".osoji/shadow/src/foo.py.shadow.md", "# src/foo.py\nDefines hello().\n")
    _write(temp_dir, ".osoji/shadow/src/_directory.shadow.md", "# src/\nThe package.\n")
    _write(temp_dir, ".osoji/shadow/_root.shadow.md", "# root\nProject overview.\n")
    _write(temp_dir, "README.md", "# Project\nUses hello.\n")

    df = _doc_finding(
        description="README claims hello() returns 2",
        shadow_ref="src/foo.py", evidence="returns 1", search_terms=["hello"],
    )
    finding = finding_from_doc(df, doc_path=Path("README.md"), root=temp_dir)
    claim = build_claims([finding], BuildContext(config))[0]

    shadow_ev = _shadow_evidence(claim)
    assert len(shadow_ev) == 1
    assert shadow_ev[0].payload["scope"] == "file"
    assert shadow_ev[0].payload["file"] == "src/foo.py"
    assert all(e.payload.get("scope") != "root" for e in shadow_ev)


def test_doc_finding_single_dir_multi_file_gets_directory_scope(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, ".osoji/shadow/src/foo.py.shadow.md", "# foo\n")
    _write(temp_dir, ".osoji/shadow/src/bar.py.shadow.md", "# bar\n")
    _write(temp_dir, ".osoji/shadow/src/_directory.shadow.md", "# src/\nPackage overview.\n")
    _write(temp_dir, "README.md", "# Project\n")

    df = _doc_finding(
        category="stale_content", severity="warning",
        description="README describes the src package layout",
        shadow_ref="src/foo.py", evidence="...", search_terms=["src/bar.py"],
    )
    finding = finding_from_doc(df, doc_path=Path("README.md"), root=temp_dir)
    claim = build_claims([finding], BuildContext(config))[0]

    shadow_ev = _shadow_evidence(claim)
    assert len(shadow_ev) == 1
    assert shadow_ev[0].payload["scope"] == "directory"
    assert shadow_ev[0].payload["file"] == "src"


def test_doc_finding_multi_dir_gets_root_scope(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, ".osoji/shadow/src/a/foo.py.shadow.md", "# a/foo\n")
    _write(temp_dir, ".osoji/shadow/src/b/bar.py.shadow.md", "# b/bar\n")
    _write(temp_dir, ".osoji/shadow/_root.shadow.md", "# root\nProject overview.\n")
    _write(temp_dir, "README.md", "# Project\n")

    df = _doc_finding(
        category="misleading_claim", severity="warning",
        description="README describes a cross-package flow",
        shadow_ref="src/a/foo.py", evidence="...", search_terms=["src/b/bar.py"],
    )
    finding = finding_from_doc(df, doc_path=Path("README.md"), root=temp_dir)
    claim = build_claims([finding], BuildContext(config))[0]

    shadow_ev = _shadow_evidence(claim)
    assert len(shadow_ev) == 1
    assert shadow_ev[0].payload["scope"] == "root"


# --- reconciliation pin -------------------------------------------------------


def test_doc_categories_resolve_to_description_schema():
    """The four doc categories are unprefixed explicit schema keys → description."""
    for cat in ("stale_content", "incorrect_content", "misleading_claim", "obsolete_reference"):
        assert gap_type_for(cat) == "description"
        df = _doc_finding(category=cat)
        finding = finding_from_doc(df, doc_path=Path("README.md"))
        key = category_of(finding)
        assert key == cat                       # unprefixed
        assert key in CLAIM_BUILDER_SCHEMA      # explicit hit, not the gap-type fallback
