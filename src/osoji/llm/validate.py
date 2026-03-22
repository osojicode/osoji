"""Lightweight JSON Schema validator for LLM tool inputs.

Validates tool call inputs against their declared schemas so we can
nudge the LLM to self-correct on schema violations before accepting
the result.  No external dependencies.
"""

from __future__ import annotations

from typing import Any

# JSON Schema type → Python types.  Note: bool is a subclass of int;
# see explicit handling in _validate.
_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),  # validated with bool exclusion below
    "number": (int, float),  # validated with bool exclusion below
    "array": (list,),
    "object": (dict,),
}


def validate_tool_input(value: Any, schema: dict) -> list[str]:
    """Validate *value* against a JSON Schema dict.

    Returns a list of human-readable error strings (empty == valid).
    Supports: type, required, enum, minimum/maximum, items, and
    recursive property/item validation with dot-path error messages.
    """
    errors: list[str] = []
    _validate(value, schema, "", errors)
    return errors


def _validate(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    schema_type = schema.get("type")
    if schema_type is None:
        return

    # --- type check ---
    if schema_type in ("integer", "number"):
        # bool is a subclass of int; reject it for integer/number
        if isinstance(value, bool):
            errors.append(_err(path, f"expected {schema_type}, got bool"))
            return
    expected = _TYPE_MAP.get(schema_type)
    if expected and not isinstance(value, expected):
        got = type(value).__name__
        errors.append(_err(path, f"expected {schema_type}, got {got}"))
        return

    # --- enum ---
    if "enum" in schema:
        if value not in schema["enum"]:
            errors.append(
                _err(path, f"value {value!r} not in enum {schema['enum']}")
            )

    # --- minimum / maximum ---
    if "minimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema["minimum"]:
            errors.append(
                _err(path, f"value {value} < minimum {schema['minimum']}")
            )
    if "maximum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > schema["maximum"]:
            errors.append(
                _err(path, f"value {value} > maximum {schema['maximum']}")
            )

    # --- required (objects) ---
    if schema_type == "object" and "required" in schema:
        for key in schema["required"]:
            if key not in value:
                errors.append(_err(path, f"missing required field '{key}'"))

    # --- properties (objects) ---
    if schema_type == "object" and "properties" in schema:
        for key, prop_schema in schema["properties"].items():
            if key in value:
                child_path = f"{path}.{key}" if path else key
                _validate(value[key], prop_schema, child_path, errors)

    # --- items (arrays) ---
    if schema_type == "array" and "items" in schema and isinstance(value, list):
        item_schema = schema["items"]
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]" if path else f"[{i}]"
            _validate(item, item_schema, child_path, errors)


def _err(path: str, message: str) -> str:
    if path:
        return f"{path}: {message}"
    return message
