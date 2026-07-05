"""Cutover gate for V1-5b: the four junk analyzers on the unified Triage pipeline.

Mirrors ``test_junk_reachability_cutover.py`` (V1-5a) for plumbing, junk_orphan,
junk_deps, and junk_cicd. A routing ``FakeProvider`` stands in for the LLM: it
serves each analyzer's *proposal* tool calls (extract/resolve/classify/entry
points/relationships) with canned proposals and the unified triage call
(``submit_triage_verdicts``) with canned verdicts, recording the system prompt
and rendered claim batch. The assertions pin the behavior the migration must
preserve or deliberately change (osojicode/work#29):

- confirmed -> reported; dismissed / uncertain -> dropped (candidates are
  hypotheses; the polarity is inverted vs debris suppression).
- prompt identity: the unified ``TRIAGE_SYSTEM_PROMPT`` — not the deleted
  per-detector verify prompts, not ``DEBRIS_TRIAGE_SYSTEM_PROMPT``.
- no legacy verify tool: the fake never serves ``verify_actuation`` /
  ``verify_orphan_files`` / ``verify_dead_deps`` / ``verify_dead_cicd``; a
  confirmed finding re-wraps to the right ``JunkFinding`` category/kind/name.
"""

import json

import pytest

from osoji.config import Config
from osoji.junk_cicd import DeadCICDAnalyzer
from osoji.junk_deps import DeadDepsAnalyzer
from osoji.junk_orphan import OrphanedFilesAnalyzer
from osoji.llm.types import CompletionResult, ToolCall
from osoji.plumbing import DeadPlumbingAnalyzer
from osoji.triage import DEBRIS_TRIAGE_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT


# --- environment helpers ------------------------------------------------------


def _write(temp_dir, rel, text):
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_symbols(temp_dir, source, symbols, file_role="service"):
    _write(
        temp_dir,
        f".osoji/symbols/{source}.symbols.json",
        json.dumps({
            "source": source,
            "source_hash": "abc",
            "file_role": file_role,
            "symbols": symbols,
        }),
    )


def _write_signature(temp_dir, source, purpose="", topics=None, public_surface=None):
    _write(
        temp_dir,
        f".osoji/signatures/{source}.signature.json",
        json.dumps({
            "path": source,
            "purpose": purpose,
            "topics": topics or [],
            "public_surface": public_surface or [],
        }),
    )


# Names of the deleted per-detector verify tools — the fake must never be asked
# to serve one of these once the analyzers run on the unified pipeline.
_LEGACY_VERIFY_TOOLS = {
    "verify_actuation",
    "verify_orphan_files",
    "verify_dead_deps",
    "verify_dead_cicd",
}


class FakeProvider:
    """Routes ``complete`` by ``options.tool_choice['name']``.

    Proposal tools return their canned input from ``proposals``; the unified
    ``submit_triage_verdicts`` call returns ``triage_verdicts`` (or all-confirmed
    when None) and records the system prompt + rendered user message.
    """

    def __init__(self, proposals, triage_verdicts=None):
        self.proposals = proposals
        self._triage_verdicts = triage_verdicts
        self.served_tools = []
        self.triage_calls = 0
        self.last_system = None
        self.last_user = None

    async def complete(self, messages, system, options):
        tool_name = (options.tool_choice or {}).get("name", "")
        self.served_tools.append(tool_name)
        assert tool_name not in _LEGACY_VERIFY_TOOLS, (
            f"analyzer called deleted verify tool {tool_name!r}"
        )

        if tool_name == "submit_triage_verdicts":
            self.triage_calls += 1
            self.last_system = system
            self.last_user = messages[0].content
            validator = options.tool_input_validators[0]
            n = len(validator("submit_triage_verdicts", {"verdicts": []}))
            if self._triage_verdicts is not None:
                verdicts = self._triage_verdicts
            else:
                verdicts = [
                    {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                     "reasoning": "unreachable"}
                    for i in range(n)
                ]
            payload = {"verdicts": verdicts}
        else:
            assert tool_name in self.proposals, f"unexpected proposal tool {tool_name!r}"
            payload = self.proposals[tool_name]

        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{len(self.served_tools)}", name=tool_name, input=payload,
            )],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="tool_use",
        )


def _assert_unified_prompt(provider):
    assert provider.triage_calls == 1
    assert provider.last_system == TRIAGE_SYSTEM_PROMPT
    assert provider.last_system != DEBRIS_TRIAGE_SYSTEM_PROMPT
    assert not (_LEGACY_VERIFY_TOOLS & set(provider.served_tools))


# --- plumbing -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_plumbing_confirmed_survives_dismissed_dropped(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "src/trial.ts",
           "const Schema = z.object({\n  taskTimeoutMs: z.number(),\n"
           "  turnTimeoutMs: z.number(),\n});\n")
    _write_symbols(temp_dir, "src/trial.ts", [], file_role="schema")
    _write(temp_dir, "src/runner.ts",
           "const t = config.taskTimeoutMs;\nconst u = config.turnTimeoutMs;\n")

    provider = FakeProvider(
        proposals={"extract_obligations": {"obligations": [
            {"field_name": "taskTimeoutMs", "schema_name": "Schema",
             "line_start": 2, "line_end": 2, "obligation": "Enforce task timeout",
             "expected_actuation": "timer/deadline"},
            {"field_name": "turnTimeoutMs", "schema_name": "Schema",
             "line_start": 3, "line_end": 3, "obligation": "Enforce turn timeout",
             "expected_actuation": "timer/deadline"},
        ]}},
        triage_verdicts=[
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9,
             "reasoning": "stored but never enforced", "suggested_fix": "add timer"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.9,
             "reasoning": "enforced via setTimeout"},
        ],
    )

    result = await DeadPlumbingAnalyzer().analyze_async(provider, config)

    _assert_unified_prompt(provider)
    assert result.total_candidates == 2
    assert [f.name for f in result.findings] == ["taskTimeoutMs"]
    f = result.findings[0]
    assert f.category == "unactuated_config"
    assert f.kind == "config_field"
    assert f.confidence == 0.9
    assert f.remediation == "add timer"
    assert f.metadata["schema_name"] == "Schema"
    assert f.confidence_source == "llm_inferred"


# --- junk_orphan --------------------------------------------------------------


def _orphan_env(temp_dir):
    """One entry point plus two disconnected files (no import edges)."""
    _write(temp_dir, "src/main.py", "def main_entry():\n    return 1\n")
    _write(temp_dir, "src/orphan_a.py", "def orphan_a():\n    return 1\n")
    _write(temp_dir, "src/orphan_b.py", "def orphan_b():\n    return 1\n")
    _write_symbols(temp_dir, "src/main.py",
                   [{"name": "main_entry", "kind": "function", "line_start": 1}],
                   file_role="entry")
    _write_symbols(temp_dir, "src/orphan_a.py",
                   [{"name": "orphan_a", "kind": "function", "line_start": 1}])
    _write_symbols(temp_dir, "src/orphan_b.py",
                   [{"name": "orphan_b", "kind": "function", "line_start": 1}])
    for p in ("src/main.py", "src/orphan_a.py", "src/orphan_b.py"):
        _write_signature(temp_dir, p, purpose="p", topics=["t"])


@pytest.mark.asyncio
async def test_orphan_confirmed_survives_dismissed_dropped(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _orphan_env(temp_dir)

    provider = FakeProvider(
        proposals={
            "identify_entry_points": {"entry_points": [
                {"source_path": "src/main.py", "is_entry_point": True, "reason": "cli"},
                {"source_path": "src/orphan_a.py", "is_entry_point": False, "reason": "lib"},
                {"source_path": "src/orphan_b.py", "is_entry_point": False, "reason": "lib"},
            ]},
            "identify_relationships": {"relationships": []},
        },
        triage_verdicts=[
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.8,
             "reasoning": "no alive pathway", "suggested_fix": "delete it"},
            {"batch_index": 1, "verdict": "uncertain", "confidence": 0.4,
             "reasoning": "cannot decide"},
        ],
    )

    result = await OrphanedFilesAnalyzer().analyze_async(provider, config)

    _assert_unified_prompt(provider)
    assert result.total_candidates == 2
    assert [f.name for f in result.findings] == ["orphan_a.py"]
    f = result.findings[0]
    assert f.category == "orphaned_file"
    assert f.kind == "file"
    assert f.source_path == "src/orphan_a.py"
    assert f.remediation == "delete it"
    assert f.confidence_source == "llm_inferred"


# --- junk_deps ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_deps_confirmed_survives_dismissed_dropped(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    _write(temp_dir, "requirements.txt", "dead-one\ndead-two\n")
    _write(temp_dir, "src/app.py", "print('nothing imported here')\n")

    provider = FakeProvider(
        proposals={
            "resolve_import_names": {"resolutions": [
                {"package_name": "dead-one", "import_names": ["dead_one"]},
                {"package_name": "dead-two", "import_names": ["dead_two"]},
            ]},
            "classify_deps": {"classifications": [
                {"package_name": "dead-one", "classification": "genuine_candidate",
                 "brief_reason": "unknown"},
                {"package_name": "dead-two", "classification": "genuine_candidate",
                 "brief_reason": "unknown"},
            ]},
        },
        triage_verdicts=[
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.85,
             "reasoning": "no import or config use", "suggested_fix": "remove it"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.9,
             "reasoning": "used as a CLI in CI"},
        ],
    )

    result = await DeadDepsAnalyzer().analyze_async(provider, config)

    _assert_unified_prompt(provider)
    assert result.total_candidates == 2
    assert [f.name for f in result.findings] == ["dead-one"]
    f = result.findings[0]
    assert f.category == "dead_dependency"
    assert f.kind == "dependency"
    assert f.source_path == "requirements.txt"
    assert f.confidence == 0.85
    assert f.metadata["usage_type"] == "unused"
    assert f.confidence_source == "llm_inferred"


# --- junk_cicd ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_cicd_confirmed_survives_dismissed_dropped(temp_dir):
    config = Config(root_path=temp_dir, respect_gitignore=False)
    # Two Makefile targets, each referencing a missing script. cicd_files is
    # passed explicitly so the run is deterministic regardless of the host
    # filesystem's case sensitivity (discover_cicd_files probes both
    # "Makefile" and "makefile").
    _write(temp_dir, "Makefile",
           "deploy:\n\tbash scripts/deploy.sh\n\npublish:\n\tbash scripts/publish.sh\n")

    provider = FakeProvider(
        proposals={},  # Makefile is parsed mechanically; no proposal LLM call
        triage_verdicts=[
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.85,
             "reasoning": "script removed", "suggested_fix": "remove target"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.9,
             "reasoning": "phony target"},
        ],
    )

    result = await DeadCICDAnalyzer().analyze_async(
        provider, config, cicd_files=[(temp_dir / "Makefile", "makefile")],
    )

    _assert_unified_prompt(provider)
    assert result.total_candidates == 2
    assert [f.name for f in result.findings] == ["deploy"]
    f = result.findings[0]
    assert f.category == "dead_cicd"
    assert f.kind == "makefile_target"
    assert f.source_path == "Makefile"
    assert f.confidence == 0.85
    assert f.confidence_source == "llm_inferred"
