"""Tests for dead plumbing detection (obligation tracing)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from docstar.config import Config
from docstar.llm.types import CompletionResult, ToolCall
from docstar.plumbing import (
    ConfigObligation,
    PlumbingResult,
    PlumbingVerification,
    _find_field_references,
    detect_dead_plumbing_async,
    extract_obligations_async,
    verify_actuation_async,
)
from docstar.rate_limiter import RateLimiter, RateLimiterConfig
from docstar.symbols import load_file_roles, load_files_by_role


# --- Helpers ---

def _write_symbols(temp_dir, source, symbols, file_role=None):
    """Helper to write a symbols JSON sidecar."""
    symbols_dir = temp_dir / ".docstar" / "symbols"
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
    shadow_dir = temp_dir / ".docstar" / "shadow"
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
        """No .docstar/symbols/ → empty dict."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        roles = load_file_roles(config)
        assert roles == {}


# --- Tests for reference scanning ---

class TestFieldReferences:
    """Tests for _find_field_references."""

    def test_finds_reference_in_other_file(self, temp_dir):
        """Field name found in another file is returned."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/schema.ts", "export const taskTimeoutMs = z.number();\n")
        _write_source(temp_dir, "src/runner.ts", "const timeout = config.taskTimeoutMs;\n")

        refs = _find_field_references(config, "taskTimeoutMs", "src/schema.ts")
        assert "src/runner.ts" in refs

    def test_excludes_defining_file(self, temp_dir):
        """The defining file itself is excluded."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/schema.ts", "export const taskTimeoutMs = z.number();\n")

        refs = _find_field_references(config, "taskTimeoutMs", "src/schema.ts")
        assert "src/schema.ts" not in refs

    def test_word_boundary(self, temp_dir):
        """Substring matches are not counted."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/schema.ts", "export const timeout = 100;\n")
        _write_source(temp_dir, "src/other.ts", "const timeoutHandler = () => {};\n")

        refs = _find_field_references(config, "timeout", "src/schema.ts")
        # "timeoutHandler" should not match "timeout" due to word boundary
        assert "src/other.ts" not in refs


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
        """Haiku extracts obligation-bearing fields from a schema."""
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


# --- Tests for actuation verification ---

class TestVerifyActuation:
    """Tests for LLM-based actuation verification (Phase B)."""

    @pytest.fixture
    def mock_provider(self):
        return AsyncMock()

    @pytest.fixture
    def config(self, temp_dir):
        return Config(root_path=temp_dir, respect_gitignore=False)

    @pytest.mark.asyncio
    async def test_unactuated_field(self, mock_provider, config):
        """Field that is only stored/passed but never enforced."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1",
                name="verify_actuation",
                input={
                    "is_actuated": False,
                    "confidence": 0.9,
                    "trace": "taskTimeoutMs is parsed from YAML, stored in config, passed to trial-runner, but never used to set a timer or deadline",
                    "remediation": "Add setTimeout with taskTimeoutMs in trial-runner.ts to enforce task-level timeout",
                },
            )],
            input_tokens=800,
            output_tokens=100,
            model="test",
            stop_reason="tool_use",
        )

        obligation = ConfigObligation(
            source_path="src/trial.ts",
            field_name="taskTimeoutMs",
            schema_name="TrialSettingsSchema",
            line_start=10,
            line_end=10,
            obligation="Enforce max elapsed time for task execution",
            expected_actuation="timer/deadline/abort/kill",
        )

        verification, in_tok, out_tok = await verify_actuation_async(
            mock_provider, config, obligation,
            "Schema shadow doc", {"src/runner.ts": "Runner shadow doc"}, {},
        )
        assert verification.is_actuated is False
        assert verification.confidence == 0.9
        assert "taskTimeoutMs" in verification.trace
        assert in_tok == 800

    @pytest.mark.asyncio
    async def test_actuated_field(self, mock_provider, config):
        """Field that is properly enforced via setTimeout."""
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1",
                name="verify_actuation",
                input={
                    "is_actuated": True,
                    "confidence": 0.95,
                    "trace": "turnTimeoutMs flows from schema → config → trial-bridge.ts where it is used in setTimeout to SIGTERM the agent process",
                    "remediation": "None needed",
                },
            )],
            input_tokens=800,
            output_tokens=100,
            model="test",
            stop_reason="tool_use",
        )

        obligation = ConfigObligation(
            source_path="src/trial.ts",
            field_name="turnTimeoutMs",
            schema_name="TrialSettingsSchema",
            line_start=11,
            line_end=11,
            obligation="Enforce max elapsed time per turn",
            expected_actuation="timer/deadline/abort/kill",
        )

        verification, _, _ = await verify_actuation_async(
            mock_provider, config, obligation,
            "Schema shadow doc", {"src/bridge.ts": "Bridge shadow doc"}, {},
        )
        assert verification.is_actuated is True
        assert verification.confidence == 0.95


# --- Integration test for full pipeline ---

class TestDetectDeadPlumbing:
    """Integration test for the full pipeline with mock LLM."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        """Full pipeline: extracts obligations, verifies actuation, returns unactuated."""
        config = Config(root_path=temp_dir, respect_gitignore=False)

        # Set up a schema file with file_role
        _write_symbols(temp_dir, "src/trial.ts", [], file_role="schema")
        _write_source(temp_dir, "src/trial.ts",
                       "const Schema = z.object({\n  taskTimeoutMs: z.number(),\n  turnTimeoutMs: z.number(),\n});")
        _write_shadow(temp_dir, "src/trial.ts", "# src/trial.ts\nSchema with timeout fields")

        # Set up a referencing file
        _write_source(temp_dir, "src/runner.ts", "const timeout = config.taskTimeoutMs;\nconst turn = config.turnTimeoutMs;\n")
        _write_shadow(temp_dir, "src/runner.ts", "# src/runner.ts\nRunner that reads config but only enforces turnTimeoutMs")

        # Mock provider: first call extracts obligations, subsequent calls verify
        mock_provider = AsyncMock()
        call_count = 0

        async def mock_complete(messages, system, options):
            nonlocal call_count
            call_count += 1
            content = messages[0].content
            if "extract_obligations" in (options.tool_choice or {}).get("name", ""):
                # Phase A: extraction
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc1",
                        name="extract_obligations",
                        input={
                            "obligations": [
                                {
                                    "field_name": "taskTimeoutMs",
                                    "schema_name": "Schema",
                                    "line_start": 2,
                                    "line_end": 2,
                                    "obligation": "Enforce task timeout",
                                    "expected_actuation": "timer/deadline",
                                },
                                {
                                    "field_name": "turnTimeoutMs",
                                    "schema_name": "Schema",
                                    "line_start": 3,
                                    "line_end": 3,
                                    "obligation": "Enforce turn timeout",
                                    "expected_actuation": "timer/deadline",
                                },
                            ],
                        },
                    )],
                    input_tokens=500, output_tokens=200,
                    model="test", stop_reason="tool_use",
                )
            elif "**Field**: `taskTimeoutMs`" in content:
                # Phase B: taskTimeoutMs is unactuated
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc2",
                        name="verify_actuation",
                        input={
                            "is_actuated": False,
                            "confidence": 0.9,
                            "trace": "taskTimeoutMs is stored but never enforced",
                            "remediation": "Add timer enforcement",
                        },
                    )],
                    input_tokens=400, output_tokens=80,
                    model="test", stop_reason="tool_use",
                )
            else:
                # Phase B: turnTimeoutMs is actuated
                return CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(
                        id="tc3",
                        name="verify_actuation",
                        input={
                            "is_actuated": True,
                            "confidence": 0.95,
                            "trace": "turnTimeoutMs is enforced via setTimeout",
                            "remediation": "None needed",
                        },
                    )],
                    input_tokens=400, output_tokens=80,
                    model="test", stop_reason="tool_use",
                )

        mock_provider.complete = mock_complete

        rate_limiter = RateLimiter(RateLimiterConfig(
            requests_per_minute=1000,
            input_tokens_per_minute=1_000_000,
            output_tokens_per_minute=1_000_000,
        ))

        result = await detect_dead_plumbing_async(
            mock_provider, rate_limiter, config,
        )

        assert isinstance(result, PlumbingResult)
        assert result.total_obligations == 2
        # Only unactuated fields should be in verifications
        unactuated_names = [r.field_name for r in result.verifications]
        assert "taskTimeoutMs" in unactuated_names
        assert "turnTimeoutMs" not in unactuated_names

    @pytest.mark.asyncio
    async def test_no_schema_files(self, temp_dir):
        """No schema files → empty results."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # Only utility files, no schemas
        _write_symbols(temp_dir, "src/utils.ts", [], file_role="utility")

        mock_provider = AsyncMock()
        rate_limiter = RateLimiter(RateLimiterConfig())

        result = await detect_dead_plumbing_async(
            mock_provider, rate_limiter, config,
        )
        assert isinstance(result, PlumbingResult)
        assert result.verifications == []
        assert result.total_obligations == 0
