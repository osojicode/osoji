"""Tests for the JSON Schema validator used for LLM tool inputs."""

import pytest

from osoji.llm.validate import validate_tool_input
from osoji.llm.types import CompletionOptions, ToolCall
from osoji.tools import SUBMIT_SHADOW_DOC_TOOL, SUBMIT_DIRECTORY_SHADOW_DOC_TOOL


class TestTypeChecking:
    """Basic type validation."""

    def test_string_valid(self):
        assert validate_tool_input("hello", {"type": "string"}) == []

    def test_string_invalid(self):
        errs = validate_tool_input(42, {"type": "string"})
        assert len(errs) == 1
        assert "expected string, got int" in errs[0]

    def test_integer_valid(self):
        assert validate_tool_input(5, {"type": "integer"}) == []

    def test_integer_rejects_float(self):
        errs = validate_tool_input(1.5, {"type": "integer"})
        assert "expected integer, got float" in errs[0]

    def test_number_accepts_int(self):
        assert validate_tool_input(5, {"type": "number"}) == []

    def test_number_accepts_float(self):
        assert validate_tool_input(0.5, {"type": "number"}) == []

    def test_number_rejects_string(self):
        errs = validate_tool_input("5", {"type": "number"})
        assert "expected number, got str" in errs[0]

    def test_boolean_valid(self):
        assert validate_tool_input(True, {"type": "boolean"}) == []
        assert validate_tool_input(False, {"type": "boolean"}) == []

    def test_array_valid(self):
        assert validate_tool_input([], {"type": "array"}) == []

    def test_array_rejects_string(self):
        errs = validate_tool_input("not-array", {"type": "array"})
        assert "expected array, got str" in errs[0]

    def test_object_valid(self):
        assert validate_tool_input({}, {"type": "object"}) == []

    def test_object_rejects_list(self):
        errs = validate_tool_input([], {"type": "object"})
        assert "expected object, got list" in errs[0]


class TestBoolIntEdgeCase:
    """bool is a subclass of int — validator must distinguish them."""

    def test_bool_rejected_for_integer(self):
        errs = validate_tool_input(True, {"type": "integer"})
        assert len(errs) == 1
        assert "got bool" in errs[0]

    def test_bool_rejected_for_number(self):
        errs = validate_tool_input(False, {"type": "number"})
        assert len(errs) == 1
        assert "got bool" in errs[0]

    def test_int_not_rejected_for_integer(self):
        assert validate_tool_input(0, {"type": "integer"}) == []
        assert validate_tool_input(1, {"type": "integer"}) == []


class TestRequiredFields:
    """required field validation on objects."""

    def test_all_present(self):
        schema = {
            "type": "object",
            "required": ["a", "b"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        }
        assert validate_tool_input({"a": "x", "b": "y"}, schema) == []

    def test_missing_field(self):
        schema = {
            "type": "object",
            "required": ["a", "b"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        }
        errs = validate_tool_input({"a": "x"}, schema)
        assert len(errs) == 1
        assert "missing required field 'b'" in errs[0]

    def test_multiple_missing(self):
        schema = {
            "type": "object",
            "required": ["a", "b", "c"],
            "properties": {},
        }
        errs = validate_tool_input({}, schema)
        assert len(errs) == 3


class TestEnum:
    """enum validation on strings."""

    def test_valid_enum(self):
        schema = {"type": "string", "enum": ["error", "warning"]}
        assert validate_tool_input("error", schema) == []

    def test_invalid_enum(self):
        schema = {"type": "string", "enum": ["error", "warning"]}
        errs = validate_tool_input("info", schema)
        assert len(errs) == 1
        assert "not in enum" in errs[0]


class TestMinMax:
    """minimum/maximum validation on numbers."""

    def test_within_range(self):
        schema = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        assert validate_tool_input(0.5, schema) == []

    def test_at_boundaries(self):
        schema = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        assert validate_tool_input(0.0, schema) == []
        assert validate_tool_input(1.0, schema) == []

    def test_below_minimum(self):
        schema = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        errs = validate_tool_input(-0.1, schema)
        assert len(errs) == 1
        assert "minimum" in errs[0]

    def test_above_maximum(self):
        schema = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        errs = validate_tool_input(1.5, schema)
        assert len(errs) == 1
        assert "maximum" in errs[0]


class TestArrayItems:
    """items validation on arrays."""

    def test_valid_items(self):
        schema = {"type": "array", "items": {"type": "string"}}
        assert validate_tool_input(["a", "b", "c"], schema) == []

    def test_invalid_item(self):
        schema = {"type": "array", "items": {"type": "string"}}
        errs = validate_tool_input(["a", 42, "c"], schema)
        assert len(errs) == 1
        assert "[1]" in errs[0]

    def test_empty_array(self):
        schema = {"type": "array", "items": {"type": "string"}}
        assert validate_tool_input([], schema) == []

    def test_string_in_object_array_rejected(self):
        """A string where items: {type: 'object'} is expected triggers an error."""
        schema = {"type": "array", "items": {"type": "object"}}
        errs = validate_tool_input(["foo", "bar"], schema)
        assert len(errs) == 2
        assert "[0]" in errs[0]
        assert "expected object" in errs[0]
        assert "got str" in errs[0]
        assert "[1]" in errs[1]


class TestNestedPaths:
    """Dot-path error messages for nested structures."""

    def test_nested_property_error(self):
        schema = {
            "type": "object",
            "properties": {
                "topic_signature": {
                    "type": "object",
                    "properties": {
                        "purpose": {"type": "string"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["purpose", "topics"],
                },
            },
        }
        # topic_signature is a string instead of object
        errs = validate_tool_input({"topic_signature": "wrong"}, schema)
        assert len(errs) == 1
        assert errs[0] == "topic_signature: expected object, got str"

    def test_deeply_nested_array_item(self):
        schema = {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["stale_comment", "dead_code"],
                            },
                        },
                        "required": ["category"],
                    },
                },
            },
        }
        data = {
            "findings": [
                {"category": "stale_comment"},
                {"category": "typo"},  # not in enum
            ]
        }
        errs = validate_tool_input(data, schema)
        assert len(errs) == 1
        assert "findings[1].category" in errs[0]
        assert "not in enum" in errs[0]

    def test_no_schema_type_skips(self):
        """Schemas without 'type' are silently accepted."""
        assert validate_tool_input("anything", {}) == []


class TestRealWorldSchemas:
    """Validate against the actual tool schemas used in production."""

    def test_valid_shadow_doc(self):
        schema = SUBMIT_SHADOW_DOC_TOOL["input_schema"]
        data = {
            "content": "# Shadow doc\nSome content here.",
            "findings": [
                {
                    "category": "stale_comment",
                    "line_start": 10,
                    "line_end": 12,
                    "severity": "warning",
                    "description": "Comment references removed function.",
                }
            ],
            "symbols": [
                {"name": "main", "kind": "function", "line_start": 1, "visibility": "public"}
            ],
            "file_role": "entry",
            "topic_signature": {
                "purpose": "Entry point for the CLI application.",
                "topics": ["cli", "argparse", "main"],
            },
        }
        assert validate_tool_input(data, schema) == []

    def test_shadow_doc_string_topic_signature(self):
        """The bug that prompted this feature: topic_signature as string."""
        schema = SUBMIT_SHADOW_DOC_TOOL["input_schema"]
        data = {
            "content": "Some content.",
            "findings": [],
            "file_role": "utility",
            "topic_signature": "This should be an object",
        }
        errs = validate_tool_input(data, schema)
        assert any("topic_signature" in e and "expected object" in e for e in errs)

    def test_shadow_doc_bad_finding_category(self):
        schema = SUBMIT_SHADOW_DOC_TOOL["input_schema"]
        data = {
            "content": "Content.",
            "findings": [
                {
                    "category": "typo",
                    "line_start": 1,
                    "line_end": 1,
                    "severity": "warning",
                    "description": "A typo.",
                }
            ],
            "file_role": "utility",
        }
        errs = validate_tool_input(data, schema)
        assert any("findings[0].category" in e and "not in enum" in e for e in errs)

    def test_shadow_doc_missing_required(self):
        schema = SUBMIT_SHADOW_DOC_TOOL["input_schema"]
        data = {"content": "Content."}  # missing findings, file_role
        errs = validate_tool_input(data, schema)
        assert any("findings" in e for e in errs)
        assert any("file_role" in e for e in errs)

    def test_valid_directory_shadow_doc(self):
        schema = SUBMIT_DIRECTORY_SHADOW_DOC_TOOL["input_schema"]
        data = {
            "content": "# Directory overview\nThis module handles...",
            "topic_signature": {
                "purpose": "LLM provider abstraction and API integration.",
                "topics": ["anthropic", "completion", "tool_use"],
            },
        }
        assert validate_tool_input(data, schema) == []

    def test_directory_shadow_doc_string_topic_signature(self):
        schema = SUBMIT_DIRECTORY_SHADOW_DOC_TOOL["input_schema"]
        data = {
            "content": "Overview.",
            "topic_signature": "Should be an object",
        }
        errs = validate_tool_input(data, schema)
        assert any("topic_signature" in e and "expected object" in e for e in errs)


class TestToolInputValidators:
    """Tests for custom tool_input_validators on CompletionOptions."""

    def test_validators_field_defaults_empty(self):
        opts = CompletionOptions(model="test")
        assert opts.tool_input_validators == []

    def test_validators_can_be_set(self):
        def my_validator(tool_name: str, tool_input: dict) -> list[str]:
            return []

        opts = CompletionOptions(model="test", tool_input_validators=[my_validator])
        assert len(opts.tool_input_validators) == 1

    def test_completeness_validator_detects_missing(self):
        """Completeness-style validator detects missing symbols."""
        expected_names = {"func_a", "func_b", "func_c"}

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "verify_dead_code":
                return []
            verdicts = tool_input.get("verdicts", [])
            got_names = {v.get("symbol_name") for v in verdicts}
            missing = expected_names - got_names
            return [f"Missing verdict for symbol '{name}'" for name in sorted(missing)]

        # Missing func_b and func_c
        errs = check_completeness("verify_dead_code", {
            "verdicts": [{"symbol_name": "func_a"}],
        })
        assert len(errs) == 2
        assert any("func_b" in e for e in errs)
        assert any("func_c" in e for e in errs)

    def test_completeness_validator_passes_when_all_present(self):
        """Completeness validator returns no errors when all symbols present."""
        expected_names = {"func_a", "func_b"}

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "verify_dead_code":
                return []
            verdicts = tool_input.get("verdicts", [])
            got_names = {v.get("symbol_name") for v in verdicts}
            missing = expected_names - got_names
            return [f"Missing verdict for symbol '{name}'" for name in sorted(missing)]

        errs = check_completeness("verify_dead_code", {
            "verdicts": [
                {"symbol_name": "func_a"},
                {"symbol_name": "func_b"},
            ],
        })
        assert errs == []

    def test_completeness_validator_ignores_other_tools(self):
        """Completeness validator ignores tool calls for other tools."""
        expected_names = {"func_a"}

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "verify_dead_code":
                return []
            verdicts = tool_input.get("verdicts", [])
            got_names = {v.get("symbol_name") for v in verdicts}
            missing = expected_names - got_names
            return [f"Missing verdict for symbol '{name}'" for name in sorted(missing)]

        errs = check_completeness("some_other_tool", {"data": "irrelevant"})
        assert errs == []

    @pytest.mark.asyncio
    async def test_validators_integrated_in_provider(self):
        """Custom validators run alongside schema validation in the provider."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch
        from osoji.llm.anthropic import AnthropicProvider

        # Use SimpleNamespace for content blocks because MagicMock(name=...)
        # sets the mock's internal _mock_name, not the .name attribute.
        first_verdicts = {
            "verdicts": [{
                "symbol_name": "func_a",
                "is_dead": True,
                "confidence": 0.9,
                "reason": "No refs",
                "remediation": "Remove",
            }],
        }
        mock_response = MagicMock()
        mock_response.content = [
            SimpleNamespace(
                type="tool_use", id="tc1",
                name="verify_dead_code", input=first_verdicts,
            ),
        ]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_response.model = "test-model"
        mock_response.stop_reason = "tool_use"

        retry_verdicts = {
            "verdicts": [
                {
                    "symbol_name": "func_a",
                    "is_dead": True,
                    "confidence": 0.9,
                    "reason": "No refs",
                    "remediation": "Remove",
                },
                {
                    "symbol_name": "func_b",
                    "is_dead": False,
                    "confidence": 0.8,
                    "reason": "Used by framework",
                    "remediation": "Keep",
                },
            ],
        }
        mock_retry_response = MagicMock()
        mock_retry_response.content = [
            SimpleNamespace(
                type="tool_use", id="tc2",
                name="verify_dead_code", input=retry_verdicts,
            ),
        ]
        mock_retry_response.usage = MagicMock(input_tokens=120, output_tokens=70)
        mock_retry_response.model = "test-model"
        mock_retry_response.stop_reason = "tool_use"

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            provider = AnthropicProvider()

        provider._client = AsyncMock()
        provider._client.messages.create = AsyncMock(
            side_effect=[mock_response, mock_retry_response]
        )

        from osoji.llm.types import Message, MessageRole
        from osoji.tools import get_dead_code_tool_definitions

        expected_names = {"func_a", "func_b"}

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "verify_dead_code":
                return []
            verdicts = tool_input.get("verdicts", [])
            got_names = {v.get("symbol_name") for v in verdicts}
            missing = expected_names - got_names
            return [f"Missing verdict for symbol '{name}'" for name in sorted(missing)]

        result = await provider.complete(
            messages=[Message(role=MessageRole.USER, content="Test")],
            system="Test system",
            options=CompletionOptions(
                model="test-model",
                max_tokens=1024,
                tools=get_dead_code_tool_definitions(),
                tool_choice={"type": "tool", "name": "verify_dead_code"},
                tool_input_validators=[check_completeness],
            ),
        )

        # Should have made 2 API calls (first + retry)
        assert provider._client.messages.create.call_count == 2

        # Result should be from the retry (which has both symbols)
        assert len(result.tool_calls) == 1
        verdicts = result.tool_calls[0].input["verdicts"]
        got_names = {v["symbol_name"] for v in verdicts}
        assert got_names == {"func_a", "func_b"}
