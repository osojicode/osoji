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
                        "line_start": {"type": "integer"},
                        "line_end": {"type": "integer"},
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
                        "line_start": {"type": "integer"},
                        "line_end": {"type": "integer"},
                    },
                    "required": ["name", "kind", "line_start"],
                },
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
        "required": ["content", "findings"],
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
                        "description": "One sentence: what this document covers. Max 30 words.",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-7 key concepts or tasks this document addresses. Short noun phrases.",
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
                    },
                    "required": [
                        "category",
                        "severity",
                        "description",
                        "evidence_shadow_path",
                        "evidence_quote",
                        "remediation",
                        "confirmed",
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


# Tool definition for dead code verification
VERIFY_DEAD_CODE_TOOL = {
    "name": "verify_dead_code",
    "description": """Determine whether a symbol is truly dead code or alive despite low/zero textual references.

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

Set is_dead=True only if the symbol has no plausible alive pathway.""",
    "input_schema": {
        "type": "object",
        "properties": {
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
        "required": ["is_dead", "confidence", "reason", "remediation"],
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
