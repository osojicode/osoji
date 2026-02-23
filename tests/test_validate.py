"""Tests for the JSON Schema validator used for LLM tool inputs."""

import pytest

from docstar.llm.validate import validate_tool_input
from docstar.tools import SUBMIT_SHADOW_DOC_TOOL, SUBMIT_DIRECTORY_SHADOW_DOC_TOOL


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
            "public_symbols": [
                {"name": "main", "kind": "function", "line_start": 1}
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
