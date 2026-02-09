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
        },
        "required": ["content"],
    },
}


# Tool definition for document classification
CLASSIFY_DOCUMENT_TOOL = {
    "name": "classify_document",
    "description": """Classify a documentation file according to the Diátaxis framework.

Determine if the file is:
- **reference**: Precise technical information (API docs, specs)
- **tutorial**: Learning-oriented walkthrough for beginners
- **how-to**: Task-oriented guide for specific goals
- **explanatory**: Understanding-oriented discussion of concepts
- **process_artifact**: Development ephemera that shouldn't be maintained

Process artifacts are "debris" - they served a purpose but aren't ongoing documentation.""",
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
            "reason": {
                "type": "string",
                "description": "Brief explanation of classification",
            },
            "remediation": {
                "type": "string",
                "description": "Action to take (e.g., 'Delete this file')",
            },
        },
        "required": ["classification", "confidence", "reason", "remediation"],
    },
}


def get_file_tools() -> list[dict]:
    """Return tools for file shadow doc generation."""
    return [SUBMIT_SHADOW_DOC_TOOL]


def get_directory_tools() -> list[dict]:
    """Return tools for directory shadow doc generation."""
    return [SUBMIT_DIRECTORY_SHADOW_DOC_TOOL]


def get_classify_tools() -> list[dict]:
    """Return tools for document classification."""
    return [CLASSIFY_DOCUMENT_TOOL]


# Tool definition for cross-reference validation
VALIDATE_CROSS_REFERENCE_TOOL = {
    "name": "submit_cross_reference_validation",
    "description": """Validate a documentation file against source-of-truth shadow docs.

Check for contradictions between what the .md file claims and what the code actually does.
Look for: wrong CLI flags, incorrect function signatures, described behaviors the code
doesn't implement, references to renamed/deleted code.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_accurate": {
                "type": "boolean",
                "description": "True if the documentation accurately reflects the source code",
            },
            "issues": {
                "type": "array",
                "description": "List of contradictions or inaccuracies found",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["error", "warning"],
                        },
                        "description": {
                            "type": "string",
                            "description": "What is wrong in the documentation",
                        },
                        "source_context": {
                            "type": "string",
                            "description": "What the source code actually does",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "How to fix the documentation",
                        },
                    },
                    "required": ["severity", "description", "source_context", "remediation"],
                },
            },
        },
        "required": ["is_accurate", "issues"],
    },
}


def get_cross_reference_tools() -> list[dict]:
    """Return tools for cross-reference validation."""
    return [VALIDATE_CROSS_REFERENCE_TOOL]


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


def get_classify_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for document classification."""
    return [_dict_to_tool_definition(CLASSIFY_DOCUMENT_TOOL)]


def get_cross_reference_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for cross-reference validation."""
    return [_dict_to_tool_definition(VALIDATE_CROSS_REFERENCE_TOOL)]
