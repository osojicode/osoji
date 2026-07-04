"""Tests for dead plumbing detection (obligation tracing)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.llm.types import CompletionResult, ToolCall
from osoji.plumbing import (
    ConfigObligation,
    detect_dead_plumbing_async,
    extract_obligations_async,
)
from osoji.symbols import load_file_roles, load_files_by_role


def _triage_verdicts(options, verdicts_by_index):
    """Build a submit_triage_verdicts ToolCall response for a triage batch.

    ``verdicts_by_index`` maps batch_index -> (verdict, confidence, reasoning).
    Missing indices default to confirmed so the whole batch is covered.
    """
    validator = options.tool_input_validators[0]
    n = len(validator("submit_triage_verdicts", {"verdicts": []}))
    verdicts = []
    for i in range(n):
        verdict, confidence, reasoning = verdicts_by_index.get(
            i, ("confirmed", 0.9, "unreachable")
        )
        verdicts.append({
            "batch_index": i, "verdict": verdict, "confidence": confidence,
            "reasoning": reasoning,
        })
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(
            id="triage", name="submit_triage_verdicts",
            input={"verdicts": verdicts},
        )],
        input_tokens=200, output_tokens=80, model="test", stop_reason="tool_use",
    )


# --- Helpers ---

def _write_symbols(temp_dir, source, symbols, file_role=None):
    """Helper to write a symbols JSON sidecar."""
    symbols_dir = temp_dir / ".osoji" / "symbols"
    sidecar = symbols_dir / (source + ".symbols.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc123",
        "generated": "2025-01-01T00:00:00Z",
        "symbols": symbols,
    }
    if file_role is not None:
        data["file_role"] = file_role
    sidecar.write_text(json.dumps(data))


def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _write_shadow(temp_dir, source, content):
    """Helper to write a shadow doc."""
    shadow_dir = temp_dir / ".osoji" / "shadow"
    shadow_file = shadow_dir / (source + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    shadow_file.write_text(content)


# --- Tests for load_file_roles / load_files_by_role ---

class TestFileRoles:
    """Tests for file_role query helpers in symbols.py."""

    def test_load_file_roles_with_roles(self, temp_dir):
        """Files with file_role are returned."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/schema.ts", [], file_role="schema")
        _write_symbols(temp_dir, "src/types.ts", [], file_role="types")
        _write_symbols(temp_dir, "src/main.ts", [], file_role="entry")

        roles = load_file_roles(config)
        assert roles == {
            "src/schema.ts": "schema",
            "src/types.ts": "types",
            "src/main.ts": "entry",
        }

    def test_load_file_roles_skips_old_cache(self, temp_dir):
        """Files without file_role key (old cache) are omitted."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/old.ts", [{"name": "foo", "kind": "function", "line_start": 1}])
        _write_symbols(temp_dir, "src/new.ts", [], file_role="service")

        roles = load_file_roles(config)
        assert "src/old.ts" not in roles
        assert roles["src/new.ts"] == "service"

    def test_load_files_by_role(self, temp_dir):
        """load_files_by_role filters correctly."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/trial.ts", [], file_role="schema")
        _write_symbols(temp_dir, "src/events.ts", [], file_role="schema")
        _write_symbols(temp_dir, "src/utils.ts", [], file_role="utility")
        _write_symbols(temp_dir, "src/main.ts", [], file_role="entry")

        schemas = load_files_by_role(config, "schema")
        assert sorted(schemas) == ["src/events.ts", "src/trial.ts"]

    def test_load_files_by_role_empty(self, temp_dir):
        """No files with the requested role returns empty list."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/utils.ts", [], file_role="utility")

        schemas = load_files_by_role(config, "schema")
        assert schemas == []

    def test_load_file_roles_no_symbols_dir(self, temp_dir):
        """No .osoji/symbols/ → empty dict."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        roles = load_file_roles(config)
        assert roles == {}

    def test_doc_json_sidecar_is_excluded_from_schema_roles(self, temp_dir):
        """Documentation JSON should stay a doc candidate, not a source schema file."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "docs/debugAdapterProtocol.json", '{"definitions": {}}')
        _write_symbols(temp_dir, "docs/debugAdapterProtocol.json", [], file_role="schema")
        _write_symbols(temp_dir, "src/runtime-schema.json", [], file_role="schema")

        assert config.is_doc_candidate(Path("docs/debugAdapterProtocol.json")) is True
        assert load_files_by_role(config, "schema") == ["src/runtime-schema.json"]


# NOTE: reference gathering used to live in plumbing's `_find_field_references`
# (with its own doc-exclusion / word-boundary coverage). V1-5b routes that job
# through `evidence_builders.CrossFileReferenceBuilder` (covered by its own
# tests) plus the cutover module; the deleted `TestFieldReferences` class is not
# re-created here.


# --- Tests for obligation extraction ---

class TestExtractObligations:
    """Tests for LLM-based obligation extraction (Phase A)."""

    @pytest.fixture
    def mock_provider(self):
        return AsyncMock()

    @pytest.fixture
    def config(self, temp_dir):
        return Config(root_path=temp_dir, respect_gitignore=False)

    @pytest.mark.asyncio
    async def test_extracts_obligations(self, mock_provider, config):
        """LLM extracts obligation-bearing fields from a schema."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1",
                name="extract_obligations",
                input={
                    "obligations": [
                        {
                            "field_name": "taskTimeoutMs",
                            "schema_name": "TrialSettingsSchema",
                            "line_start": 10,
                            "line_end": 10,
                            "obligation": "Enforce max elapsed time for task execution",
                            "expected_actuation": "timer/deadline/abort/kill",
                        },
                        {
                            "field_name": "turnTimeoutMs",
                            "schema_name": "TrialSettingsSchema",
                            "line_start": 11,
                            "line_end": 11,
                            "obligation": "Enforce max elapsed time per turn",
                            "expected_actuation": "timer/deadline/abort/kill",
                        },
                    ],
                },
            )],
            input_tokens=500,
            output_tokens=200,
            model="test",
            stop_reason="tool_use",
        )

        obligations, in_tok, out_tok = await extract_obligations_async(
            mock_provider, config,
            "src/trial.ts",
            "const TrialSettingsSchema = z.object({\n  taskTimeoutMs: z.number(),\n  turnTimeoutMs: z.number(),\n});",
            "Shadow doc content",
        )
        assert len(obligations) == 2
        assert obligations[0].field_name == "taskTimeoutMs"
        assert obligations[0].schema_name == "TrialSettingsSchema"
        assert obligations[1].field_name == "turnTimeoutMs"
        assert in_tok == 500
        assert out_tok == 200

    @pytest.mark.asyncio
    async def test_empty_obligations(self, mock_provider, config):
        """Schema with no obligation-bearing fields returns empty list."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1",
                name="extract_obligations",
                input={"obligations": []},
            )],
            input_tokens=300,
            output_tokens=50,
            model="test",
            stop_reason="tool_use",
        )

        obligations, _, _ = await extract_obligations_async(
            mock_provider, config,
            "src/types.ts",
            "interface Config {\n  name: string;\n  description: string;\n}",
            "",
        )
        assert obligations == []


# --- Integration test for full pipeline (unified Triage) ---

class TestDetectDeadPlumbing:
    """Integration test for the full pipeline with mock LLM.

    Actuation judgment now lives in the unified Triage stage: extraction
    proposes obligations, the Claim Builder assembles cross-file references,
    and ``submit_triage_verdicts`` decides confirmed (unactuated) vs dismissed.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        """Extract obligations, then Triage confirms the unactuated field only."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        _write_symbols(temp_dir, "src/trial.ts", [], file_role="schema")
        _write_source(temp_dir, "src/trial.ts",
                      "const Schema = z.object({\n  taskTimeoutMs: z.number(),\n"
                      "  turnTimeoutMs: z.number(),\n});")
        _write_shadow(temp_dir, "src/trial.ts", "# src/trial.ts\nSchema with timeout fields")
        _write_source(temp_dir, "src/runner.ts",
                      "const timeout = config.taskTimeoutMs;\n"
                      "const turn = config.turnTimeoutMs;\n")

        mock_provider = AsyncMock()

        async def mock_complete(messages, system, options):
            tool_name = (options.tool_choice or {}).get("name", "")
            if tool_name == "extract_obligations":
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc1", name="extract_obligations",
                        input={"obligations": [
                            {"field_name": "taskTimeoutMs", "schema_name": "Schema",
                             "line_start": 2, "line_end": 2,
                             "obligation": "Enforce task timeout",
                             "expected_actuation": "timer/deadline"},
                            {"field_name": "turnTimeoutMs", "schema_name": "Schema",
                             "line_start": 3, "line_end": 3,
                             "obligation": "Enforce turn timeout",
                             "expected_actuation": "timer/deadline"},
                        ]},
                    )],
                    input_tokens=500, output_tokens=200,
                    model="test", stop_reason="tool_use",
                )
            # Triage: taskTimeoutMs (index 0) unactuated -> confirmed;
            # turnTimeoutMs (index 1) enforced -> dismissed.
            return _triage_verdicts(options, {
                0: ("confirmed", 0.9, "stored but never enforced"),
                1: ("dismissed", 0.95, "enforced via setTimeout"),
            })

        mock_provider.complete = mock_complete

        decided, total = await detect_dead_plumbing_async(mock_provider, config)

        assert total == 2
        confirmed = [f for f in decided if f.verdict == "confirmed"]
        assert [f.symbol for f in confirmed] == ["taskTimeoutMs"]

    @pytest.mark.asyncio
    async def test_no_schema_files(self, temp_dir):
        """No schema files → empty results, no LLM calls."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_symbols(temp_dir, "src/utils.ts", [], file_role="utility")

        mock_provider = AsyncMock()

        decided, total = await detect_dead_plumbing_async(mock_provider, config)
        assert (decided, total) == ([], 0)
        assert mock_provider.complete.await_count == 0

    @pytest.mark.asyncio
    async def test_doc_json_schema_sidecar_does_not_trigger_plumbing(self, temp_dir):
        """A docs/*.json sidecar marked schema should not enter dead-plumbing analysis."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "docs/debugAdapterProtocol.json", '{"definitions": {}}')
        _write_symbols(temp_dir, "docs/debugAdapterProtocol.json", [], file_role="schema")

        mock_provider = AsyncMock()

        decided, total = await detect_dead_plumbing_async(mock_provider, config)

        assert (decided, total) == ([], 0)
        assert mock_provider.complete.await_count == 0
