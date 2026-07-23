"""Tests for the Triage LLM tool schemas (V1-3).

These pin the contract the Triage stage and its tests negotiate against: the
claim-mode batch tool keyed by ``batch_index`` (collision-safe — symbol-less
debris findings can share ``finding.id``), the exploration terminal verdict
tool, and the three read-only exploration tools.
"""

from osoji.tools import (
    get_triage_claim_tool_definitions,
    get_triage_exploration_tool_definitions,
)

_VERDICTS = ("confirmed", "dismissed", "uncertain")
_SEVERITIES = ("error", "warning", "info")
# Authority-source contract taxonomy (ratified 2026-07-22): classify by WHO
# defines the binding, not by what carries it. The literal-shaped predecessors
# are retired.
_CONTRACT_CLASSES = (
    "project_named", "project_implicit", "ecosystem", "coincidental", "other",
)
_RETIRED_CONTRACT_CLASSES = (
    "named_obligation", "unnamed_obligation", "ecosystem_convention",
    "magic_constant", "coincidence",
)


def _verdict_item_props(tool):
    return tool.input_schema["properties"]["verdicts"]["items"]["properties"]


def test_claim_tool_name_and_batch_index_key():
    [tool] = get_triage_claim_tool_definitions()
    assert tool.name == "submit_triage_verdicts"
    item = tool.input_schema["properties"]["verdicts"]["items"]
    props = item["properties"]
    # Mapping back to the source finding is by explicit batch index, not finding_id.
    assert "batch_index" in props
    assert "finding_id" not in props
    for required in ("batch_index", "verdict", "confidence", "reasoning"):
        assert required in item["required"]


def test_claim_tool_verdict_and_severity_enums():
    [tool] = get_triage_claim_tool_definitions()
    props = _verdict_item_props(tool)
    assert tuple(props["verdict"]["enum"]) == _VERDICTS
    assert tuple(props["severity"]["enum"]) == _SEVERITIES


def test_claim_tool_contract_class_enum_is_authority_source_taxonomy():
    [tool] = get_triage_claim_tool_definitions()
    props = _verdict_item_props(tool)
    enum = tuple(props["contract_class"]["enum"])
    assert enum == _CONTRACT_CLASSES
    # The retired literal-shaped classes must not linger in the schema.
    for old in _RETIRED_CONTRACT_CLASSES:
        assert old not in enum


def test_exploration_tools_present():
    tools = {t.name for t in get_triage_exploration_tool_definitions()}
    assert tools == {"read_file", "grep", "list_dir", "submit_triage_verdict"}


def test_exploration_verdict_tool_is_singular():
    [verdict] = [
        t for t in get_triage_exploration_tool_definitions()
        if t.name == "submit_triage_verdict"
    ]
    props = verdict.input_schema["properties"]
    # Single-claim terminal: a verdict, no batch_index.
    assert "verdict" in props
    assert "batch_index" not in props
    assert tuple(props["verdict"]["enum"]) == _VERDICTS


def test_read_file_tool_schema():
    [read] = [
        t for t in get_triage_exploration_tool_definitions() if t.name == "read_file"
    ]
    props = read.input_schema["properties"]
    assert "path" in props
    assert "path" in read.input_schema["required"]
