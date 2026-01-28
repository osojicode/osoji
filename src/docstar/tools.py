"""Tool definitions for LLM-forced output."""

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
        },
        "required": ["content"],
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
