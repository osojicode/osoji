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
                "description": "Code quality issues found during analysis. Report stale comments, misleading docstrings, commented-out code blocks, expired TODOs, dead code, and latent bugs. Always include this field, using an empty array if none are found.",
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
                                "latent_bug",
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
                        "valid": {
                            "type": "boolean",
                            "default": True,
                            "description": (
                                "Set to false to retract this finding if on reflection "
                                "it is incorrect. Defaults to true."
                            ),
                        },
                        "cross_file_verification_needed": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "Set true when this finding references behavior in OTHER files "
                                "that cannot be verified from the current file alone."
                            ),
                        },
                    },
                    "required": ["category", "line_start", "line_end", "severity", "description"],
                },
            },
            "symbols": {
                "type": "array",
                "description": "All symbols defined in this file — both public/exported and internal/private. Include functions, classes, constants, and module-level variables.",
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
                        "visibility": {
                            "type": "string",
                            "enum": ["public", "internal"],
                            "description": "public = importable/exported API; internal = private helpers, underscored functions, file-local utilities",
                        },
                        "parameters": {
                            "type": "array",
                            "description": "For function/method symbols: list all parameters. Omit for classes, constants, variables.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Parameter name"},
                                    "optional": {
                                        "type": "boolean",
                                        "description": "true if parameter has a default value or is typed as optional (e.g. = None, ?: , Optional[T], default arguments in any language)",
                                    },
                                },
                                "required": ["name", "optional"],
                            },
                        },
                    },
                    "required": ["name", "kind", "line_start", "visibility"],
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
            "imports": {
                "type": "array",
                "description": "All imports in this file.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Import specifier as written (relative path, package name, stdlib module)",
                        },
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Imported identifiers. Use [\"default\"] for default imports, [\"*\"] for wildcard.",
                        },
                        "is_reexport": {
                            "type": "boolean",
                            "description": "True if imported only to re-export (barrel files, __init__.py re-exports)",
                        },
                    },
                    "required": ["source", "names", "is_reexport"],
                },
            },
            "exports": {
                "type": "array",
                "description": "Public API surface — names importable by other files.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["function", "class", "constant", "variable", "type"],
                        },
                        "line": {"type": "integer", "minimum": 1},
                    },
                    "required": ["name", "kind", "line"],
                },
            },
            "calls": {
                "type": "array",
                "description": "Significant cross-file function/method calls from exported symbols and module-level code. Skip same-file and internal helper calls.",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_symbol": {
                            "type": "string",
                            "description": "Calling function/method name. Use \"<module>\" for top-level calls.",
                        },
                        "to": {
                            "type": "string",
                            "description": "Target identifier: module.function, ClassName.method, or package.function",
                        },
                        "line": {"type": "integer", "minimum": 1},
                        "call_sites": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Number of distinct call sites across the project; omit if unknown.",
                        },
                    },
                    "required": ["from_symbol", "to", "line"],
                },
            },
            "member_writes": {
                "type": "array",
                "description": "Cross-file relevant writes to object/class/dataclass fields, e.g. obj.status = 'done'. Include writes that could prove a field is used from another file.",
                "items": {
                    "type": "object",
                    "properties": {
                        "container": {
                            "type": "string",
                            "description": "Object/expression whose member is written, e.g. 'scorecard' or 'result.metrics'",
                        },
                        "member": {
                            "type": "string",
                            "description": "Field/property name being written",
                        },
                        "line": {"type": "integer", "minimum": 1},
                    },
                    "required": ["container", "member", "line"],
                },
            },
            "string_literals": {
                "type": "array",
                "description": "Notable string constants that participate in cross-file contracts: identifiers, messages, config values. NOT every string — skip file paths, import specifiers, docstrings, test data, filename/path sentinels, serialized-data keys, and external protocol literals.",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "context": {
                            "type": "string",
                            "description": "Brief description of how this string is used",
                        },
                        "line": {"type": "integer", "minimum": 1},
                        "kind": {
                            "type": "string",
                            "enum": ["identifier", "message", "config", "pattern"],
                            "description": "identifier = project-internal name, category, discriminant, "
                                           "or action verb used in dispatch/routing within this project's own code; "
                                           "message = user-facing or log text; "
                                           "config = fixed external protocol value, database code, MIME type, "
                                           "environment name, HTTP method/status, third-party SDK constant, "
                                           "or any value whose meaning is defined OUTSIDE this project; "
                                           "pattern = regex or glob pattern.",
                        },
                        "usage": {
                            "type": "string",
                            "enum": ["produced", "checked", "defined", "external_input", "unknown"],
                            "description": "produced = emitted/returned/appended, including dict/mapping values, "
                                           "default parameter values, collection literal elements, "
                                           "and type union/literal type members (TypeScript union literals, Python Literal types) "
                                           "(these are all production sites even if the same string is also checked); "
                                           "checked = membership test/equality against an internal project value; "
                                           "defined = assigned to constant; "
                                           "external_input = string enters from outside the project at runtime "
                                           "(environment variables, CLI arguments/flags, HTTP request fields, "
                                           "DOM/browser events, wire protocol method names, OS signals) — "
                                           "not hardcoded string literals; "
                                           "unknown = can't tell. "
                                           "Always skip well-known external conventions (language names, test framework "
                                           "patterns, standard extensions), filename/path sentinels, serialized-data "
                                           "keys, and external protocol literals — do not extract them.",
                        },
                        "comparison_source": {
                            "type": "string",
                            "description": "What the string is compared against. For 'checked' strings: the variable or expression on the other side of ==, in, not in, .get(), etc. Examples: 'tool_call.name', 'os.environ', 'schema[key]', 'analyzer.name'. Omit for non-checked strings.",
                        },
                    },
                    "required": ["value", "context", "line", "kind", "usage"],
                },
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
Report findings with evidence from shadow docs. Always include the `findings` field, using an empty array if no issues are found.""",
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


def get_extract_obligations_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for obligation extraction."""
    return [_dict_to_tool_definition(EXTRACT_OBLIGATIONS_TOOL)]


# --- Phase 3: Haiku-backed analysis tools ---

# Tool definition for batch import name resolution (Haiku)
RESOLVE_IMPORT_NAMES_TOOL = {
    "name": "resolve_import_names",
    "description": """Resolve package names to their importable module names.

For each package, return the name(s) that would appear in import statements.
Examples:
- pillow (python) → ["PIL"]
- scikit-learn (python) → ["sklearn"]
- beautifulsoup4 (python) → ["bs4"]
- serde-json (rust) → ["serde_json"]
- @scope/pkg (node) → ["@scope/pkg"]

If a package installs multiple importable names, list all of them.
If you don't know the import name, use the heuristic: lowercase, hyphens to underscores.

Provide a resolution for EVERY package listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "package_name": {
                            "type": "string",
                            "description": "The package name as given",
                        },
                        "import_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Importable module name(s) for this package",
                        },
                    },
                    "required": ["package_name", "import_names"],
                },
            },
        },
        "required": ["resolutions"],
    },
}


# Tool definition for batch dependency classification (Haiku)
CLASSIFY_DEPS_TOOL = {
    "name": "classify_deps",
    "description": """Classify zero-import dependencies by their usage pattern.

For each dependency that has zero import matches in source code, determine HOW it is used:

- **build_tool**: Invoked from CLI, not imported (black, ruff, pytest, eslint, webpack, cargo-edit)
- **plugin**: Auto-discovered by a framework (pytest-cov, babel-plugin-*, postcss-*)
- **cli_tool**: Provides a command-line binary (alembic, celery, gunicorn, nodemon)
- **type_package**: Type stubs only (@types/*, types-requests, mypy type stubs)
- **build_system**: Required by build backend (setuptools, wheel, hatchling, flit-core)
- **genuine_candidate**: None of the above — this dependency MAY be truly unused

Only `genuine_candidate` items will proceed to further verification. Be conservative:
if a package is clearly a build tool or plugin, classify it as such to avoid false positives.

Provide a classification for EVERY dependency listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "package_name": {
                            "type": "string",
                            "description": "The package name being classified",
                        },
                        "classification": {
                            "type": "string",
                            "enum": [
                                "build_tool", "plugin", "cli_tool",
                                "type_package", "build_system", "genuine_candidate",
                            ],
                        },
                        "brief_reason": {
                            "type": "string",
                            "description": "One-line explanation of the classification",
                        },
                    },
                    "required": ["package_name", "classification", "brief_reason"],
                },
            },
        },
        "required": ["classifications"],
    },
}


# Tool definition for CI/CD element extraction (Haiku)
EXTRACT_CICD_ELEMENTS_TOOL = {
    "name": "extract_cicd_elements",
    "description": """Extract structured elements from a CI/CD configuration file.

Parse the file and identify each discrete pipeline element (job, stage, target, etc.).
For each element, extract:
- Name and type
- Line range in the file
- Any file paths referenced (scripts, directories, config files)
- Any commands or actions referenced

Be thorough — extract ALL elements, not just the first few.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_name": {
                            "type": "string",
                            "description": "Name of the pipeline element",
                        },
                        "element_type": {
                            "type": "string",
                            "description": "Type of element (e.g. 'job', 'stage', 'pipeline', 'step')",
                        },
                        "line_start": {"type": "integer", "minimum": 1},
                        "line_end": {"type": "integer", "minimum": 1},
                        "referenced_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "File paths or directories referenced by this element",
                        },
                        "referenced_commands": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Commands or actions this element runs",
                        },
                    },
                    "required": [
                        "element_name", "element_type",
                        "line_start", "line_end",
                        "referenced_paths", "referenced_commands",
                    ],
                },
            },
        },
        "required": ["elements"],
    },
}


# Tool definition for entry point identification (Haiku)
IDENTIFY_ENTRY_POINTS_TOOL = {
    "name": "identify_entry_points",
    "description": """Identify which source files are entry points in the project.

An entry point is a file that is invoked directly rather than imported by other files:
- CLI scripts and main modules (__main__.py, bin scripts, console_scripts)
- Test files (test_*.py, *_test.py, *.test.ts, spec files)
- Framework endpoints (Django views registered in urls.py, Flask app files)
- Configuration files that are loaded by tools (conftest.py, setup.py, manage.py)
- Build/task scripts (Makefile targets, task runners)
- Package __init__.py files (entry point for the package namespace)

Use the file_role hint as a signal but make your own judgment based on the full context.

Provide a verdict for EVERY file listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "entry_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Relative path of the file",
                        },
                        "is_entry_point": {
                            "type": "boolean",
                            "description": "True if this file is an entry point",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation",
                        },
                    },
                    "required": ["source_path", "is_entry_point", "reason"],
                },
            },
        },
        "required": ["entry_points"],
    },
}


# Tool definition for semantic relationship identification (Haiku)
IDENTIFY_RELATIONSHIPS_TOOL = {
    "name": "identify_relationships",
    "description": """Identify semantic relationships between disconnected files and the connected graph.

You are given two lists:
1. **disconnected**: Files not reachable via import edges from any entry point
2. **connected**: Files that ARE reachable

For each disconnected file, determine if it semantically relates to any connected file
based on their purposes and topics. A relationship means the disconnected file likely
supports, extends, or is used by the connected file through non-import mechanisms
(dynamic loading, convention-based discovery, configuration, etc.).

Only report relationships you are confident about. It is OK to leave a disconnected
file without any relationship — that means it may be orphaned.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Path of the disconnected file",
                        },
                        "related_to": {
                            "type": "string",
                            "description": "Path of the connected file it relates to",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why these files are related",
                        },
                    },
                    "required": ["source_path", "related_to", "reason"],
                },
            },
        },
        "required": ["relationships"],
    },
}


def get_resolve_import_names_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for import name resolution."""
    return [_dict_to_tool_definition(RESOLVE_IMPORT_NAMES_TOOL)]


def get_classify_deps_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for dependency classification."""
    return [_dict_to_tool_definition(CLASSIFY_DEPS_TOOL)]


def get_extract_cicd_elements_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for CI/CD element extraction."""
    return [_dict_to_tool_definition(EXTRACT_CICD_ELEMENTS_TOOL)]


def get_identify_entry_points_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for entry point identification."""
    return [_dict_to_tool_definition(IDENTIFY_ENTRY_POINTS_TOOL)]


def get_identify_relationships_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for semantic relationship identification."""
    return [_dict_to_tool_definition(IDENTIFY_RELATIONSHIPS_TOOL)]


# --- Phase 5.5: Documentation prompts tools ---

BUILD_CONCEPT_INVENTORY_TOOL = {
    "name": "build_concept_inventory",
    "description": """Build a codebase concept inventory from file-level topic signatures.

Each concept represents a coherent, documentable unit. Cluster related files into
higher-level concepts, classify each concept's role, and determine which Diataxis
documentation types are appropriate.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept_id": {
                            "type": "string",
                            "description": "URL-safe slug, e.g. 'breakpoint-lifecycle'",
                        },
                        "concept_name": {
                            "type": "string",
                            "description": "Human-readable name, e.g. 'Breakpoint Lifecycle'",
                        },
                        "concept_description": {
                            "type": "string",
                            "description": "1-2 sentence description of this concept",
                        },
                        "source_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Source file paths contributing to this concept",
                        },
                        "concept_role": {
                            "type": "string",
                            "enum": [
                                "public_api", "cli_command", "configuration",
                                "architectural_pattern", "internal_utility",
                                "integration_point", "data_model",
                                "error_handling", "testing_infrastructure",
                            ],
                        },
                        "appropriate_doc_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["reference", "tutorial", "how-to", "explanatory"],
                            },
                        },
                        "appropriateness_rationale": {
                            "type": "string",
                            "description": "Why these doc types are appropriate for this concept",
                        },
                    },
                    "required": [
                        "concept_id", "concept_name", "concept_description",
                        "source_files", "concept_role", "appropriate_doc_types",
                        "appropriateness_rationale",
                    ],
                },
            },
        },
        "required": ["concepts"],
    },
}


GENERATE_WRITING_PROMPTS_TOOL = {
    "name": "generate_writing_prompts",
    "description": """Generate self-contained writing prompts for documentation gaps.

For each gap (concept × missing Diataxis type), produce a prompt that another agent
can execute without re-auditing the codebase. Include task, audience, scope, quality
criteria, and consistency guidance.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "prompt_id": {
                            "type": "string",
                            "description": "Unique ID, e.g. 'breakpoint-lifecycle-tutorial'",
                        },
                        "target_concept_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "concept_ids covered by this prompt (usually 1, >1 for clusters)",
                        },
                        "diataxis_type": {
                            "type": "string",
                            "enum": ["reference", "tutorial", "how-to", "explanatory"],
                        },
                        "prompt_text": {
                            "type": "string",
                            "description": "Complete, self-contained writing prompt",
                        },
                        "scope_constraints": {
                            "type": "string",
                            "description": "What is in/out of scope for this doc",
                        },
                        "output_guidance": {
                            "type": "object",
                            "properties": {
                                "suggested_filename": {"type": "string"},
                                "suggested_directory": {"type": "string"},
                            },
                        },
                    },
                    "required": [
                        "prompt_id", "target_concept_ids", "diataxis_type",
                        "prompt_text", "scope_constraints", "output_guidance",
                    ],
                },
            },
        },
        "required": ["prompts"],
    },
}


def get_concept_inventory_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for concept inventory building."""
    return [_dict_to_tool_definition(BUILD_CONCEPT_INVENTORY_TOOL)]


def get_writing_prompts_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for writing prompt generation."""
    return [_dict_to_tool_definition(GENERATE_WRITING_PROMPTS_TOOL)]


# --- V1-3: Unified Triage stage tools ---
#
# The Triage stage verifies a batch of self-sufficient claims against the
# TP predicates (reality / actionability; significance grades severity,
# never the verdict — work#59). Two output
# tools: a batch tool for claim mode and a single-verdict terminal tool for
# exploration mode. Plus three read-only retrieval tools for exploration mode,
# executed by ``osoji.triage_exec.ExplorationExecutor``.

# Shared verdict-field schema (a single claim's outcome). batch_index is added
# only to the batch tool; exploration's terminal tool decides one claim and has
# no index.
_TRIAGE_VERDICT_FIELDS = {
    "verdict": {
        "type": "string",
        "enum": ["confirmed", "dismissed", "uncertain"],
        "description": "confirmed = the gap is real and actionable (grade how much it "
                       "matters via severity); dismissed = false positive; "
                       "uncertain = evidence insufficient to decide.",
    },
    "confidence": {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
        "description": "Confidence in the verdict (1.0 = certain).",
    },
    "reasoning": {
        "type": "string",
        "description": "The reasoning trace for this verdict — captured verbatim onto the "
                       "finding. Weigh the evidence against reality and actionability.",
    },
    "suggested_fix": {
        "type": "string",
        "description": "Concrete remediation if confirmed (e.g. 'remove the function', "
                       "'use the existing MAX_RETRIES constant'). Omit or empty if dismissed.",
    },
    "severity": {
        "type": "string",
        "enum": ["error", "warning", "info"],
        "description": "Severity of the confirmed finding — this is where significance "
                       "lives: 'info' marks a real-but-minor finding (demoted, never "
                       "dismissed, for insignificance). Omit if dismissed.",
    },
    "contract_class": {
        "type": "string",
        "enum": [
            "named_obligation", "unnamed_obligation", "ecosystem_convention",
            "magic_constant", "coincidence", "other",
        ],
        "description": "CONTRACT-gap claims only: the string-contract class of the shared "
                       "literal. Emit 'other' when no class fits — a request for review, never "
                       "shoehorned into the nearest class. Omit for non-contract claims.",
    },
}


# Claim mode: one call returns a verdict for every claim in the batch, keyed by
# batch_index (the claim's 0-based position in the submitted batch). The index —
# not finding.id — is the join key, because symbol-less debris findings can share
# an id; the index is always unambiguous.
SUBMIT_TRIAGE_VERDICTS_TOOL = {
    "name": "submit_triage_verdicts",
    "description": """Submit a triage verdict for EVERY claim in the batch.

Each claim is a gap hypothesis (reachability / description / contract) with evidence
assembled for you. Decide each against the two true-positive predicates:
- Reality: does the gap actually exist in the code, now?
- Actionability: is there a concrete fix?
Significance grades the confirmed finding's severity (real-but-minor = 'info');
it is never grounds for dismissal.

Return one verdict per claim, identified by its batch_index. When a claim shows a
Symbol line, echo it in the verdict's symbol field — sibling claims (e.g. two
parameters of the same function) are easy to cross-wire by index alone.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "batch_index": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "0-based index of the claim being judged, as listed in the prompt.",
                        },
                        "symbol": {
                            "type": "string",
                            "description": "The claim's Symbol line, echoed exactly as shown. "
                                           "Omit for claims without one.",
                        },
                        **_TRIAGE_VERDICT_FIELDS,
                    },
                    "required": ["batch_index", "verdict", "confidence", "reasoning"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


# Exploration mode terminal tool: decide the single claim under exploration.
SUBMIT_TRIAGE_VERDICT_TOOL = {
    "name": "submit_triage_verdict",
    "description": """Submit the final verdict for the single claim under exploration.

Call this once you have gathered enough evidence with read_file / grep / list_dir to
decide the claim against the two predicates (reality / actionability); significance
grades the confirmed finding's severity, never the verdict.""",
    "input_schema": {
        "type": "object",
        "properties": dict(_TRIAGE_VERDICT_FIELDS),
        "required": ["verdict", "confidence", "reasoning"],
    },
}


# Exploration retrieval tools — read-only, executed against the repo root by
# ExplorationExecutor. Schemas are intentionally minimal.
READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a file in the repository. Optionally restrict to a 1-based, "
                   "inclusive line range with start/end.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative file path."},
            "start": {"type": "integer", "minimum": 1, "description": "First line (1-based, inclusive)."},
            "end": {"type": "integer", "minimum": 1, "description": "Last line (1-based, inclusive)."},
        },
        "required": ["path"],
    },
}

GREP_TOOL = {
    "name": "grep",
    "description": "Search file contents under the repository root for a regular expression. "
                   "Returns path:line: text rows.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "A regular expression."},
            "glob": {"type": "string", "description": "Optional glob to restrict files, e.g. '**/*.py'."},
        },
        "required": ["pattern"],
    },
}

LIST_DIR_TOOL = {
    "name": "list_dir",
    "description": "List the entries of a directory under the repository root.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative directory path (default repo root)."},
        },
        "required": [],
    },
}


def get_triage_claim_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for claim-mode batch triage."""
    return [_dict_to_tool_definition(SUBMIT_TRIAGE_VERDICTS_TOOL)]


def get_triage_exploration_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for exploration mode (retrieval + terminal verdict)."""
    return [
        _dict_to_tool_definition(READ_FILE_TOOL),
        _dict_to_tool_definition(GREP_TOOL),
        _dict_to_tool_definition(LIST_DIR_TOOL),
        _dict_to_tool_definition(SUBMIT_TRIAGE_VERDICT_TOOL),
    ]
