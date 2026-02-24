"""Tool definitions for LLM-forced output."""

from typing import Any

from .llm.types import ToolDefinition


# Tool definition for file shadow documentation
SUBMIT_SHADOW_DOC_TOOL = {
    "name": "submit_shadow_doc",
    "description": """Submit a shadow documentation summary for a source file.

The shadow doc should be a semantically dense summary optimized for AI agent consumption.
Include:
- Primary purpose and responsibility of the file
- Key classes, functions, and their roles (with line numbers)
- Important dependencies and relationships
- Notable patterns or architectural decisions
- Any critical invariants or constraints

Be concise but comprehensive. Focus on what an AI agent would need to understand
to work with this code effectively.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The shadow documentation content (markdown format, without header)",
            },
            "findings": {
                "type": "array",
                "description": "Code quality issues found during analysis. Report stale comments, misleading docstrings, commented-out code blocks, and expired TODOs. Empty array if none found.",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "stale_comment",
                                "misleading_docstring",
                                "commented_out_code",
                                "expired_todo",
                                "dead_code",
                            ],
                        },
                        "line_start": {"type": "integer", "minimum": 1},
                        "line_end": {"type": "integer", "minimum": 1},
                        "severity": {
                            "type": "string",
                            "enum": ["error", "warning"],
                        },
                        "description": {"type": "string"},
                        "suggestion": {
                            "type": "string",
                            "description": "What should be done to fix this issue",
                        },
                    },
                    "required": ["category", "line_start", "line_end", "severity", "description"],
                },
            },
            "public_symbols": {
                "type": "array",
                "description": "Public symbols (functions, classes, constants) defined in this file that could be imported or used by other files. Exclude private/underscore-prefixed names unless they are part of the module's public API (e.g., _matches_ignore used cross-module).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Symbol name as it appears in code",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["function", "class", "constant", "variable"],
                        },
                        "line_start": {"type": "integer", "minimum": 1},
                        "line_end": {"type": "integer", "minimum": 1},
                    },
                    "required": ["name", "kind", "line_start"],
                },
            },
            "file_role": {
                "type": "string",
                "enum": [
                    "schema",
                    "types",
                    "config",
                    "service",
                    "adapter",
                    "utility",
                    "test",
                    "entry",
                ],
                "description": (
                    "Classify this file's primary architectural role:\n"
                    "- schema: Defines validated data shapes with runtime enforcement "
                    "(Zod, Pydantic, JSON Schema, protobuf, marshmallow, io-ts)\n"
                    "- types: Type-only definitions without runtime validation "
                    "(interfaces, type aliases, enums, .d.ts)\n"
                    "- config: Configuration loading, parsing, resolution, "
                    "environment variable handling\n"
                    "- service: Core business logic, orchestration, controllers, "
                    "domain operations\n"
                    "- adapter: External system integration — I/O, APIs, databases, "
                    "file system, network\n"
                    "- utility: Stateless helpers, formatters, pure functions, "
                    "shared constants\n"
                    "- test: Test files (unit, integration, e2e)\n"
                    "- entry: CLI entry points, main files, script runners"
                ),
            },
            "topic_signature": {
                "type": "object",
                "description": "Fixed-format summary for coverage analysis",
                "properties": {
                    "purpose": {
                        "type": "string",
                        "description": "One sentence: what this file/module does. Max 30 words.",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-7 key concepts, features, or responsibilities. Short noun phrases.",
                    },
                },
                "required": ["purpose", "topics"],
            },
        },
        "required": ["content", "findings", "file_role"],
    },
}

# Tool definition for directory roll-up shadow documentation
SUBMIT_DIRECTORY_SHADOW_DOC_TOOL = {
    "name": "submit_directory_shadow_doc",
    "description": """Submit a shadow documentation summary for a directory.

This is a roll-up summary synthesizing the shadow docs of all files in the directory.
Include:
- Overall purpose and responsibility of this module/package
- Key components and how they relate
- Public API surface (main entry points)
- Internal organization and data flow
- Important patterns or conventions

Be concise but comprehensive. Focus on helping an AI agent understand the
module's role in the larger system.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The directory shadow documentation content (markdown format, without header)",
            },
            "topic_signature": {
                "type": "object",
                "description": "Fixed-format summary for coverage analysis",
                "properties": {
                    "purpose": {
                        "type": "string",
                        "description": "One sentence: what this directory/module does. Max 30 words.",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-7 key concepts, features, or responsibilities. Short noun phrases.",
                    },
                },
                "required": ["purpose", "topics"],
            },
        },
        "required": ["content"],
    },
}


# Tool definition for topic matching (Haiku)
MATCH_DOC_TOPICS_TOOL = {
    "name": "match_doc_topics",
    "description": """Return the source file paths whose code is relevant to this documentation file.

Review the doc content and the directory summaries provided. Select directories whose
code is discussed, referenced, or relevant to the documentation — even if the doc
doesn't explicitly name the files.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Source file paths whose code is relevant to this doc",
            },
            "topic_signature": {
                "type": "object",
                "description": "Fixed-format summary for coverage analysis",
                "properties": {
                    "purpose": {
                        "type": "string",
                        "description": "One sentence: what this documentation covers. Max 30 words.",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-7 key concepts, features, or responsibilities. Short noun phrases.",
                    },
                },
                "required": ["purpose", "topics"],
            },
        },
        "required": ["relevant_paths"],
    },
}


# Tool definition for unified document analysis (Sonnet)
ANALYZE_DOCUMENT_TOOL = {
    "name": "analyze_document",
    "description": """Classify a documentation file and validate its accuracy against shadow docs.

Classification (Diataxis framework):
- **reference**: Precise technical information (API docs, specs, ADRs, design docs)
- **tutorial**: Learning-oriented walkthrough for beginners
- **how-to**: Task-oriented guide for specific goals
- **explanatory**: Understanding-oriented discussion of concepts
- **process_artifact**: Inherently temporary file created for a one-time action

A document with outdated content but ongoing purpose is stale, not debris. Classify it under its Diataxis category.

Validation: check for contradictions between the doc and the shadow docs (source of truth).
Report findings with evidence from shadow docs. Empty findings array if no issues found.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["reference", "tutorial", "how-to", "explanatory", "process_artifact"],
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "classification_reason": {
                "type": "string",
                "description": "Brief explanation of classification",
            },
            "findings": {
                "type": "array",
                "description": "Accuracy issues found by comparing doc against shadow docs. Empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "stale_content",
                                "incorrect_content",
                                "obsolete_reference",
                                "misleading_claim",
                            ],
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["error", "warning"],
                        },
                        "description": {
                            "type": "string",
                            "description": "What is wrong in the documentation",
                        },
                        "evidence_shadow_path": {
                            "type": "string",
                            "description": "Source path of shadow doc providing evidence",
                        },
                        "evidence_quote": {
                            "type": "string",
                            "description": "Brief quote from shadow doc that contradicts the doc",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "How to fix the documentation",
                        },
                        "confirmed": {
                            "type": "boolean",
                            "description": "Set to true only if this is a genuine contradiction. Set to false if on reflection the doc and shadow docs are consistent, the evidence is inconclusive, or no action is needed.",
                        },
                        "search_terms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Technical identifiers this finding makes claims about "
                                           "(command names, function names, config keys, flags, etc.). "
                                           "These will be searched across the full project for verification.",
                        },
                    },
                    "required": [
                        "category",
                        "severity",
                        "description",
                        "evidence_shadow_path",
                        "evidence_quote",
                        "remediation",
                        "confirmed",
                        "search_terms",
                    ],
                },
            },
        },
        "required": ["classification", "confidence", "classification_reason", "findings"],
    },
}


def get_file_tools() -> list[dict]:
    """Return tools for file shadow doc generation."""
    return [SUBMIT_SHADOW_DOC_TOOL]


def get_directory_tools() -> list[dict]:
    """Return tools for directory shadow doc generation."""
    return [SUBMIT_DIRECTORY_SHADOW_DOC_TOOL]


def get_match_doc_topics_tools() -> list[dict]:
    """Return tools for doc topic matching."""
    return [MATCH_DOC_TOPICS_TOOL]


# Tool definition for dead code verification (batch: array of verdicts)
VERIFY_DEAD_CODE_TOOL = {
    "name": "verify_dead_code",
    "description": """Determine whether each listed symbol is truly dead code or alive despite low/zero textual references.

## False positives for grep hits (hit exists but is NOT a real usage)
- **Comments**: The symbol name appears only inside a comment or docstring
- **String literals**: Appears in a string, log message, or error message
- **Name collision**: A different module/class defines a symbol with the same name
- **Similar-but-different**: Substring match on a longer identifier (e.g. `run` inside `run_tests`)
- **Type annotations only**: Used only in type hints, never called at runtime

## False negatives for zero-reference symbols (no hits but symbol IS alive)
- **Decorators / framework magic**: @app.route, @pytest.fixture, @property, signal handlers
- **Convention-based dispatch**: Django views, Flask endpoints, Click commands, test_ methods
- **Dynamic dispatch**: getattr(), importlib, plugin registries, __getattr__
- **Dunder methods**: __init__, __str__, __enter__, __eq__ — called implicitly
- **__all__ exports**: Listed in __all__ for public API
- **Entry points**: setup.py/pyproject.toml console_scripts, main() functions
- **Callbacks / hooks**: Registered at runtime, passed as arguments
- **Overrides**: Abstract method implementations, interface conformance
- **Re-exports**: Imported in __init__.py for public API surface

Set is_dead=True only if the symbol has no plausible alive pathway.
Provide a verdict for EVERY symbol listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol_name": {
                            "type": "string",
                            "description": "Name of the symbol being judged",
                        },
                        "is_dead": {
                            "type": "boolean",
                            "description": "True if the symbol is genuinely dead code with no alive pathway",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence in the is_dead judgment (1.0 = certain)",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of why the symbol is dead or alive",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "Suggested action (e.g. 'Remove function' or 'Keep — used by framework')",
                        },
                    },
                    "required": ["symbol_name", "is_dead", "confidence", "reason", "remediation"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


def get_dead_code_tools() -> list[dict]:
    """Return tools for dead code verification."""
    return [VERIFY_DEAD_CODE_TOOL]


def _dict_to_tool_definition(tool_dict: dict[str, Any]) -> ToolDefinition:
    """Convert a tool dictionary to a ToolDefinition object."""
    return ToolDefinition(
        name=tool_dict["name"],
        description=tool_dict["description"],
        input_schema=tool_dict["input_schema"],
    )


def get_file_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for file shadow doc generation."""
    return [_dict_to_tool_definition(SUBMIT_SHADOW_DOC_TOOL)]


def get_directory_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for directory shadow doc generation."""
    return [_dict_to_tool_definition(SUBMIT_DIRECTORY_SHADOW_DOC_TOOL)]


def get_match_doc_topics_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for doc topic matching."""
    return [_dict_to_tool_definition(MATCH_DOC_TOPICS_TOOL)]


def get_analyze_document_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for unified document analysis."""
    return [_dict_to_tool_definition(ANALYZE_DOCUMENT_TOOL)]


def get_dead_code_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for dead code verification."""
    return [_dict_to_tool_definition(VERIFY_DEAD_CODE_TOOL)]


# Tool definition for doc finding verification (Sonnet, per document with errors)
VERIFY_DOC_FINDING_TOOL = {
    "name": "verify_doc_finding",
    "description": """Re-evaluate documentation error findings given additional project evidence.

You are given the original error-severity findings from a documentation analysis, plus
grep evidence gathered from project files that were NOT available during the initial analysis.

For each finding, decide:
- **upheld**: The finding is correct — the additional evidence confirms or does not contradict it.
- **retracted**: The finding is a false positive — the additional evidence shows the documented
  claim is actually correct (e.g. a command IS registered as an entry point, a config key DOES exist).
- **downgraded**: The finding has some merit but the additional evidence makes it less certain.
  Downgrade from error to warning severity.

Provide a verdict for EVERY finding listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "finding_index": {
                            "type": "integer",
                            "description": "0-based index of the finding being judged",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["upheld", "retracted", "downgraded"],
                            "description": "Whether to keep, remove, or downgrade the finding",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of the verdict",
                        },
                    },
                    "required": ["finding_index", "action", "reason"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


def get_verify_doc_finding_tools() -> list[dict]:
    """Return tools for doc finding verification."""
    return [VERIFY_DOC_FINDING_TOOL]


def get_verify_doc_finding_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for doc finding verification."""
    return [_dict_to_tool_definition(VERIFY_DOC_FINDING_TOOL)]


# Tool definition for obligation extraction (Haiku, per schema file)
EXTRACT_OBLIGATIONS_TOOL = {
    "name": "extract_obligations",
    "description": """Identify fields in a schema file that declare behavioral obligations.

An "obligation" is a field whose name and context promise the system will enforce a runtime
behavior. Examples: timeout fields, rate limits, max retries, size limits.

Exclude purely descriptive or identity fields (name, description, id, label, etc.)
and purely quantitative fields with no enforcement implication (count, total, etc.).

For each obligation-bearing field, describe what enforcement the system should perform
and what actuation pattern would satisfy the obligation.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "obligations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {
                            "type": "string",
                            "description": "The field name as it appears in the schema",
                        },
                        "schema_name": {
                            "type": "string",
                            "description": "The schema/type name containing this field",
                        },
                        "line_start": {"type": "integer"},
                        "line_end": {
                            "type": "integer",
                            "description": "End line of the field definition (may be same as line_start)",
                        },
                        "obligation": {
                            "type": "string",
                            "description": "What the field promises the system will enforce at runtime",
                        },
                        "expected_actuation": {
                            "type": "string",
                            "description": "What enforcement code would look like (e.g. 'timer/deadline/abort/kill', 'counter check/loop guard')",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Direct quote from the schema text (description, comment, or constraint) "
                                           "that establishes this obligation. If you cannot quote specific text, "
                                           "this is NOT an obligation.",
                        },
                    },
                    "required": [
                        "field_name",
                        "schema_name",
                        "line_start",
                        "line_end",
                        "obligation",
                        "expected_actuation",
                        "evidence",
                    ],
                },
            },
        },
        "required": ["obligations"],
    },
}


# Tool definition for actuation verification (Sonnet, per obligation)
VERIFY_ACTUATION_TOOL = {
    "name": "verify_actuation",
    "description": """Determine whether a config field's declared obligation is actually enforced at runtime.

You are given:
1. An obligation-bearing config field and its promise
2. Shadow docs for all files that reference the field
3. Shadow docs for sibling fields from the same schema (as positive counterexamples)

Trace the field from its schema definition through all referencing files. Determine whether
any code actually USES the value to CAUSE the declared effect (actuation), or whether the
value is only stored, passed, restructured, and logged without enforcement.

Key distinctions:
- Passing a value to a library function documented to enforce it IS actuation (e.g. axios({timeout: value}))
- Logging or displaying a value is NOT actuation
- Storing for later retrieval is NOT actuation (unless retrieval leads to enforcement)
- Cross-process handoff (env vars → container → subprocess) IS actuation if receiving side enforces""",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_actuated": {
                "type": "boolean",
                "description": "True if the obligation is enforced at runtime somewhere in the codebase",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the is_actuated judgment (1.0 = certain)",
            },
            "trace": {
                "type": "string",
                "description": "Description of the data flow: where the field is defined, passed, and (if actuated) where enforcement happens. If unactuated, describe the gap.",
            },
            "remediation": {
                "type": "string",
                "description": "Suggested fix if unactuated (e.g. 'Add setTimeout with taskTimeoutMs in trial-runner.ts'). 'None needed' if actuated.",
            },
        },
        "required": ["is_actuated", "confidence", "trace", "remediation"],
    },
}


def get_extract_obligations_tools() -> list[dict]:
    """Return tools for obligation extraction."""
    return [EXTRACT_OBLIGATIONS_TOOL]


def get_verify_actuation_tools() -> list[dict]:
    """Return tools for actuation verification."""
    return [VERIFY_ACTUATION_TOOL]


def get_extract_obligations_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for obligation extraction."""
    return [_dict_to_tool_definition(EXTRACT_OBLIGATIONS_TOOL)]


def get_verify_actuation_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for actuation verification."""
    return [_dict_to_tool_definition(VERIFY_ACTUATION_TOOL)]
