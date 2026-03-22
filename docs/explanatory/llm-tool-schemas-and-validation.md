# LLM Tool Schemas and Validation: Structured Output from Language Models

Osoji's code analysis pipeline requires structured data from LLMs -- not prose summaries, but typed fields with specific shapes: arrays of findings with severity enums, symbol lists with line ranges, confidence scores between 0 and 1. This document explains how Osoji achieves reliable structured output using tool schemas and a validation layer that enables LLM self-correction.

## The problem: getting structured data from LLMs

LLMs produce free-form text by default. An audit pipeline that parses prose with regex is fragile and error-prone. Osoji needs machine-readable output: findings with categories from a fixed set, symbols with integer line numbers, file roles from an enum, obligation pairs with confidence scores. The output must conform to a predictable shape so downstream code can process it without defensive parsing.

## Tool-use protocol as structured output

Osoji uses the LLM tool-calling protocol not to execute tools, but to force structured output. The technique works as follows:

1. A tool is defined with a JSON Schema describing its input parameters
2. The LLM is instructed to "call" the tool via `tool_choice: {"type": "tool", "name": "submit_shadow_doc"}`
3. The LLM produces output conforming to the schema (the tool's "input")
4. Osoji extracts the structured data from the `ToolCall.input` dict

The LLM never actually executes anything. The tool definition is a schema contract that constrains the LLM's output format. This approach works across all major LLM providers because tool calling is a widely supported protocol.

## Schema catalog in `tools.py`

Tool definitions are organized as module-level dict constants in `src/osoji/tools.py`. Each dict follows the `{"name": ..., "description": ..., "input_schema": {...}}` structure. Accessor functions convert these dicts into `ToolDefinition` dataclass instances using the `_dict_to_tool_definition()` helper pattern, providing type safety at call sites.

### Phase 1 -- Shadow Documentation

`SUBMIT_SHADOW_DOC_TOOL` is the richest schema in the system. It defines the structure for per-file shadow documentation and captures:

- `content` (string) -- the shadow doc body in markdown
- `findings` (array) -- code quality issues, each with `category` (enum: `stale_comment`, `misleading_docstring`, `commented_out_code`, `expired_todo`, `dead_code`, `latent_bug`), `line_start`, `line_end`, `severity` (enum: `error`, `warning`), `description`, optional `suggestion`, `valid` (boolean for self-retraction), and `cross_file_verification_needed`
- `symbols` (array) -- all defined symbols with `name`, `kind` (enum: `function`, `class`, `constant`, `variable`), `line_start`, `line_end`, `visibility` (enum: `public`, `internal`), and optional `parameters` array
- `file_role` (enum: `schema`, `types`, `config`, `service`, `adapter`, `utility`, `test`, `entry`) -- architectural classification
- `topic_signature` (object) -- `purpose` string and `topics` array for coverage analysis
- `imports`, `exports`, `calls`, `member_writes`, `string_literals` -- structured facts for cross-file analysis

The directory-level equivalent, `SUBMIT_DIRECTORY_SHADOW_DOC_TOOL`, captures a `content` string and `topic_signature` for roll-up summaries.

### Phase 2 -- Doc Analysis

- Doc analysis tools -- schemas for evaluating documentation accuracy against code

### Phase 3 -- Debris Verification

- Debris verification tools -- schemas for confirming or rejecting code quality findings with cross-file evidence

### Phase 3.5 -- Obligations

- Obligation checking is pure Python (no LLM calls, no tool schemas). It uses the FactsDB to detect implicit string contracts across files.

### Phase 4 -- Junk Detection Tools

Each junk analyzer has corresponding tool schemas:

- Dead code verification -- `get_dead_code_tool_definitions()` provides schemas for LLM-based confirmation of unused symbols
- Dead parameter verification -- `get_dead_parameter_tool_definitions()` for confirming function parameters no caller passes
- Dead plumbing verification -- schemas for confirming unactuated configuration obligations
- Dead CI/CD verification -- `get_dead_cicd_tool_definitions()` for stale pipeline element confirmation
- Dead dependency verification -- `get_dead_deps_tool_definitions()` for unused package dependency confirmation
- Orphan file verification -- schemas for confirming files with no reachable purpose

### Phase 5.5 -- Doc Prompts

- Concept inventory building -- schemas for structured topic extraction
- Writing prompt generation -- schemas for documentation gap analysis

### The accessor pattern

Each schema group has a `get_*_tool_definitions()` function that returns `list[ToolDefinition]`. For example, `get_file_tool_definitions()` returns a list containing the `ToolDefinition` built from `SUBMIT_SHADOW_DOC_TOOL`. This pattern keeps schemas as static data (module-level dicts are evaluated once) while providing typed accessors that callers use.

## The validation layer: `llm/validate.py`

Osoji includes a lightweight, zero-dependency JSON Schema validator purpose-built for validating LLM tool call outputs.

### Public interface

`validate_tool_input(value, schema) -> list[str]` is the entry point. It takes a parsed value (typically a dict from `ToolCall.input`) and a JSON Schema dict, returning a list of human-readable error strings. An empty list means the value is valid.

### Recursive validation

The internal `_validate(value, schema, path, errors)` function handles:

- **Type checking** -- validates against `string`, `boolean`, `integer`, `number`, `array`, `object`
- **Enum validation** -- checks that values are in the allowed set
- **Range validation** -- `minimum` and `maximum` for numeric types
- **Required fields** -- checks that all required keys are present in objects
- **Nested properties** -- recursively validates each property against its sub-schema
- **Array items** -- recursively validates each element against the `items` schema
- **Dot-path error messages** -- errors include the path to the failing field (e.g., `findings[2].line_start: expected integer, got string`)

### The bool/int subclass problem

Python's `bool` is a subclass of `int`: `isinstance(True, int)` returns `True`. Without special handling, a boolean value would pass validation for `integer` and `number` schema types. The validator explicitly rejects booleans for these types:

```python
if schema_type in ("integer", "number"):
    if isinstance(value, bool):
        errors.append(_err(path, f"expected {schema_type}, got bool"))
        return
```

This is a concrete example of why a custom validator matters -- the standard `jsonschema` library handles this correctly, but the custom validator also produces error messages optimized for LLM consumption rather than developer debugging.

### Why not the `jsonschema` library?

Three reasons drove the decision to build a custom validator:

1. **Zero dependencies.** The validator adds no external dependencies to Osoji's core.
2. **Subset sufficiency.** Osoji's schemas use a small subset of JSON Schema (type, required, enum, minimum/maximum, properties, items). Supporting the full spec would add complexity without benefit.
3. **Human-readable errors optimized for LLM self-correction.** This is the most important reason, and it connects directly to the self-correction loop.

## The self-correction loop

The key insight behind the validation architecture: validation error messages are not just for developers -- they are prompts for the LLM to fix its own mistakes.

When `LiteLLMProvider.complete()` receives a tool call response, it validates the output against the schema. If validation fails, the provider:

1. Constructs a feedback message listing all validation errors as bullet points
2. Appends the LLM's original response and the error feedback to the conversation
3. Asks the LLM to re-call the tool with corrected values
4. Repeats up to `_MAX_TOOL_VALIDATION_ATTEMPTS` (3) times

The conversation sent back to the LLM looks like:

```
[tool_result, is_error=True]
Schema validation errors - please re-call the tool with corrected values:
- findings[0].severity: value "high" not in enum ["error", "warning"]
- symbols[2].line_start: expected integer, got string
```

Because the error messages use plain language and dot-path notation, the LLM can understand exactly which fields failed and how to fix them. This is why `_err()` produces prose-like strings (`"expected integer, got string"`) rather than machine-structured error objects -- the LLM is the consumer.

The retry loop in `LiteLLMProvider.complete()` also handles the case where the LLM fails to call the required tool at all. If `tool_choice` forces a specific tool but the response lacks that tool call, the provider sends a reminder message and optionally doubles `max_tokens` if the stop reason was `"length"` (the LLM may have run out of output space before emitting the tool call). The `_build_tool_feedback()` helper constructs the validation error messages for tool calls that were made but contained schema violations.

### Custom validators beyond schema

`CompletionOptions.tool_input_validators` allows callers to register additional validation functions beyond JSON Schema. For example, the junk framework's `validate_line_ranges()` function checks that `line_end >= line_start` across findings arrays -- a semantic constraint that JSON Schema's `minimum`/`maximum` cannot express across fields. These custom validators run alongside schema validation and their errors are included in the self-correction feedback.

## Design decisions and trade-offs

**Why module-level dicts plus accessor functions?** Schemas are static data that never changes at runtime. Defining them as module-level dicts means they are evaluated once at import time. The accessor functions (`get_file_tool_definitions()`, etc.) wrap the dicts in `ToolDefinition` dataclasses, providing type safety without runtime overhead. This pattern also makes schemas easy to find -- they are all in `tools.py`, not scattered across the modules that use them.

**Schema strictness vs. flexibility.** The schemas enforce structure (required fields, type constraints, enums) but allow optional fields and additional properties. This balance catches genuine errors (wrong types, missing fields, invalid enum values) while accommodating LLM variation in optional output. The `valid` field on findings, for example, lets the LLM retract a finding it included by mistake rather than requiring perfect classification on the first pass.

**The centrality of `tools.py`.** Many modules depend on tool schemas: `shadow.py` for shadow generation, `audit.py` for debris verification, `deadcode.py` and other junk analyzers for verification, `doc_analysis.py` for accuracy evaluation, `doc_prompts.py` for concept inventory. Changes to a schema in `tools.py` affect all consumers. This centralization is deliberate -- it ensures consistency across all phases that use the same data shapes.

For how the `ToolDefinition` and `ToolCall` types integrate with the provider abstraction, see the [LLM provider abstraction](llm-provider-abstraction.md) document. For how schemas are used in shadow documentation generation, see the [shadow documentation architecture](shadow-documentation-architecture.md) document.
