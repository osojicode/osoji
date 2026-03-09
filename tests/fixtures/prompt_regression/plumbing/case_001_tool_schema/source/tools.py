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
                    },
                    "required": ["from_symbol", "to", "line"],
                },
            },
            "string_literals": {
                "type": "array",
                "description": "Notable string constants that participate in cross-file contracts: identifiers (keys, names, categories), messages, config values. NOT every string — skip file paths, import specifiers, docstrings, test data.",
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
                        },
                        "usage": {
                            "type": "string",
                            "enum": ["produced", "checked", "defined", "unknown"],
                            "description": "produced = emitted/returned/appended, including dict/mapping values, default parameter values, and collection literal elements; checked = membership test/equality; defined = assigned to constant; unknown = can't tell. Skip well-known external conventions (language names, test framework patterns, standard extensions) that have no internal producer.",
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
- **Dunder / magic methods**: __init__, __str__, __enter__, __eq__ — called implicitly
- **Explicit public API exports**: Python __all__ / __init__.py re-exports; JS/TS export in
  barrel files; Rust pub use re-exports; Go capitalized identifiers
- **Entry points**: setup.py/pyproject.toml console_scripts, main() functions, bin scripts
- **Callbacks / hooks**: Registered at runtime, passed as arguments
- **Overrides**: Abstract method implementations, interface conformance
- **Trait implementations**: Rust impl Trait for Type — invoked implicitly
- **FFI / generated code**: #[derive], #[no_mangle], extern "C" exports
- **Within-file transitive liveness**: A symbol is alive if an externally-referenced symbol
  in the same file directly or indirectly USES it — even through chains of private helper
  functions (constant used inside a private function called by a public function; dataclass
  returned by an exported API). Liveness flows FROM the entry point INTO what it uses —
  a sibling function that merely references the same constant is NOT alive through this path.

**Key rule**: A zero-reference wrapper function is DEAD even if it returns a constant/tool
that IS used by other functions. "It looks like framework code" or "it wraps something used"
are NOT valid reasons — if the function itself has zero call sites, it is dead.

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


def get_extract_obligations_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for obligation extraction."""
    return [_dict_to_tool_definition(EXTRACT_OBLIGATIONS_TOOL)]


def get_verify_actuation_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for actuation verification."""
    return [_dict_to_tool_definition(VERIFY_ACTUATION_TOOL)]


# Tool definition for dead dependency verification (batch: array of verdicts)
VERIFY_DEAD_DEPS_TOOL = {
    "name": "verify_dead_deps",
    "description": """Determine whether each listed dependency is truly unused or alive despite having zero import matches.

## Common reasons a zero-import dependency is ALIVE
- **Build tool / linter / formatter**: Invoked via CLI scripts, pre-commit hooks, or CI commands (e.g. black, ruff, pytest, eslint, prettier)
- **Framework plugin**: Auto-discovered by a framework (pytest plugins, Django apps, Babel/PostCSS plugins)
- **CLI tool**: Provides a command-line binary used in scripts (e.g. alembic, celery, gunicorn)
- **Type stubs / @types packages**: Used only by the type checker, no runtime import
- **Peer dependency**: Required by another package but not directly imported
- **Build system requirement**: Needed by the build backend (setuptools, wheel, hatchling)
- **Import name mismatch**: The package installs under a different import name not checked

## When a dependency IS dead
- No imports found AND not a build tool, plugin, CLI tool, type package, or peer dep
- Package was added for a feature that was later removed
- Duplicate of another package providing the same functionality

Set is_dead=True only if the dependency has no plausible alive pathway.
Provide a verdict for EVERY dependency listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "package_name": {
                            "type": "string",
                            "description": "Name of the package being judged",
                        },
                        "is_dead": {
                            "type": "boolean",
                            "description": "True if the dependency is genuinely unused",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence in the is_dead judgment (1.0 = certain)",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of why the dependency is dead or alive",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "Suggested action (e.g. 'Remove from dependencies' or 'Keep — pytest plugin')",
                        },
                        "usage_type": {
                            "type": "string",
                            "enum": ["import", "build_tool", "plugin", "cli_tool", "peer_dep", "type_package", "unused"],
                            "description": "How the dependency is used (or 'unused' if dead)",
                        },
                    },
                    "required": ["package_name", "is_dead", "confidence", "reason", "remediation", "usage_type"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


def get_dead_deps_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for dead dependency verification."""
    return [_dict_to_tool_definition(VERIFY_DEAD_DEPS_TOOL)]


# Tool definition for dead CI/CD verification (batch: array of verdicts)
VERIFY_DEAD_CICD_TOOL = {
    "name": "verify_dead_cicd",
    "description": """Determine whether each listed CI/CD element is stale/dead or still active.

## Signals that an element IS dead
- References paths/directories that no longer exist in the repo
- Builds or tests a subproject that has been deleted
- Deploys to an environment that has been decommissioned
- Runs scripts that reference removed files or commands
- Duplicates another job/target without additional value

## Signals that an element is ALIVE
- Installs dependencies (pip install, npm install) — these are inherently external
- Runs test frameworks (pytest, jest, cargo test) — test discovery is dynamic
- Deploys using external tools (aws, gcloud, kubectl) — targets are external
- Runs linters/formatters on the repo (paths may be implicit)
- Uses external actions/images that don't reference local paths
- Makefile targets used as dependencies by other targets

Missing paths are the PRIMARY signal, but not all commands reference local paths.
Evaluate each element holistically.
Provide a verdict for EVERY element listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_name": {
                            "type": "string",
                            "description": "Name of the CI/CD element being judged",
                        },
                        "is_dead": {
                            "type": "boolean",
                            "description": "True if the element is stale/dead",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence in the is_dead judgment (1.0 = certain)",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of why the element is dead or alive",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "Suggested action (e.g. 'Remove job' or 'Keep — deploys to production')",
                        },
                    },
                    "required": ["element_name", "is_dead", "confidence", "reason", "remediation"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


def get_dead_cicd_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for dead CI/CD verification."""
    return [_dict_to_tool_definition(VERIFY_DEAD_CICD_TOOL)]


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


# Tool definition for orphan file verification (Sonnet)
VERIFY_ORPHAN_FILES_TOOL = {
    "name": "verify_orphan_files",
    "description": """Determine whether each listed file is truly orphaned or alive despite being unreachable in the purpose graph.

## Common reasons an unreachable file is ALIVE
- **Plugin / extension**: Loaded dynamically by a framework (pytest plugins, Django apps, Flask extensions)
- **Dynamic import**: Loaded via importlib, __import__, or similar mechanisms
- **Convention-based**: Framework discovers it by naming convention (test files, migration files, template files)
- **Configuration target**: Referenced in config files (entry_points, console_scripts, tool configs)
- **Script / CLI**: Invoked directly from command line or CI/CD, not imported

## When a file IS orphaned
- No imports from other files AND no dynamic loading mechanism
- Was part of a feature that was later removed
- Duplicate of another file providing the same functionality
- Experimental/scratch file that was never integrated

Set is_orphaned=True only if the file has no plausible alive pathway.
Provide a verdict for EVERY file listed.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Relative path of the file being judged",
                        },
                        "is_orphaned": {
                            "type": "boolean",
                            "description": "True if the file is genuinely orphaned",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of why the file is orphaned or alive",
                        },
                        "remediation": {
                            "type": "string",
                            "description": "Suggested action (e.g. 'Delete file' or 'Keep — pytest plugin')",
                        },
                    },
                    "required": ["source_path", "is_orphaned", "confidence", "reason", "remediation"],
                },
            },
        },
        "required": ["verdicts"],
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


def get_verify_orphan_files_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition objects for orphan file verification."""
    return [_dict_to_tool_definition(VERIFY_ORPHAN_FILES_TOOL)]
