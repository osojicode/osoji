# src\osoji\tools.py
@source-hash: a92fc8f0e37574f7
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:12Z

## Purpose
Defines all LLM tool schemas (JSON Schema-based input_schema dicts) used to force structured outputs from LLM calls throughout the osoji pipeline, plus factory functions that convert them into `ToolDefinition` objects.

## Architecture
All tools follow the same pattern:
1. A module-level `dict` constant defines the raw tool schema (`name`, `description`, `input_schema`)
2. A private `_dict_to_tool_definition()` helper (L480–486) converts any such dict to a `ToolDefinition` via `ToolDefinition(name=..., description=..., input_schema=...)`
3. Public `get_*_tool_definitions()` factory functions wrap the conversion and return `list[ToolDefinition]`

## Tool Constants and Their Factory Functions

| Constant | Lines | Factory | Purpose |
|---|---|---|---|
| `SUBMIT_SHADOW_DOC_TOOL` | L9–298 | `get_file_tool_definitions()` L489–491 | LLM tool for emitting per-file shadow docs (content, findings, symbols, file_role, topic_signature, imports, exports, calls, member_writes, string_literals) |
| `SUBMIT_DIRECTORY_SHADOW_DOC_TOOL` | L301–341 | `get_directory_tool_definitions()` L494–496 | LLM tool for emitting directory roll-up shadow docs |
| `MATCH_DOC_TOPICS_TOOL` | L345–379 | `get_match_doc_topics_tool_definitions()` L499–501 | Haiku tool: maps documentation files to relevant source file paths |
| `ANALYZE_DOCUMENT_TOOL` | L383–476 | `get_analyze_document_tool_definitions()` L504–506 | Sonnet tool: Diataxis classification + accuracy validation of docs against shadow docs |
| `EXTRACT_OBLIGATIONS_TOOL` | L510–572 | `get_extract_obligations_tool_definitions()` L575–577 | Haiku tool: identifies behavioral obligation fields in schema files |
| `RESOLVE_IMPORT_NAMES_TOOL` | L583–623 | `get_resolve_import_names_tool_definitions()` L824–826 | Haiku tool: resolves package names to importable module names |
| `CLASSIFY_DEPS_TOOL` | L627–674 | `get_classify_deps_tool_definitions()` L829–831 | Haiku tool: classifies zero-import dependencies (build_tool, plugin, cli_tool, type_package, build_system, genuine_candidate) |
| `EXTRACT_CICD_ELEMENTS_TOOL` | L678–729 | `get_extract_cicd_elements_tool_definitions()` L834–836 | Haiku tool: extracts pipeline elements from CI/CD config files |
| `IDENTIFY_ENTRY_POINTS_TOOL` | L733–775 | `get_identify_entry_points_tool_definitions()` L839–841 | Haiku tool: classifies source files as entry points or not |
| `IDENTIFY_RELATIONSHIPS_TOOL` | L779–821 | `get_identify_relationships_tool_definitions()` L844–846 | Haiku tool: finds semantic relationships between disconnected and connected files |
| `BUILD_CONCEPT_INVENTORY_TOOL` | L851–914 | `get_concept_inventory_tool_definitions()` L973–975 | Builds a codebase concept inventory for doc gap analysis (Phase 5.5) |
| `GENERATE_WRITING_PROMPTS_TOOL` | L917–970 | `get_writing_prompts_tool_definitions()` L978–980 | Generates self-contained writing prompts for documentation gaps |
| `_TRIAGE_VERDICT_FIELDS` | L995–1036 | — | Shared dict of verdict field schemas (verdict, confidence, reasoning, suggested_fix, severity, contract_class); spread into triage tools |
| `SUBMIT_TRIAGE_VERDICTS_TOOL` | L1043–1083 | `get_triage_claim_tool_definitions()` L1146–1148 | Batch claim-mode triage: one verdict per claim, keyed by `batch_index` |
| `SUBMIT_TRIAGE_VERDICT_TOOL` | L1087–1099 | `get_triage_exploration_tool_definitions()` L1151–1158 | Single-verdict terminal tool for exploration mode |
| `READ_FILE_TOOL` | L1104–1117 | `get_triage_exploration_tool_definitions()` | Read-only file retrieval for exploration mode |
| `GREP_TOOL` | L1119–1131 | `get_triage_exploration_tool_definitions()` | Regex search tool for exploration mode |
| `LIST_DIR_TOOL` | L1133–1143 | `get_triage_exploration_tool_definitions()` | Directory listing for exploration mode |

## Key Design Details
- `_TRIAGE_VERDICT_FIELDS` (L995–1036) is a plain `dict` spread with `**` into both triage tool schemas (L1075, L1096), enabling DRY verdict field sharing without duplication.
- The stale comment at L479 (`# Tool definition for dead code verification (batch: array of verdicts)`) is leftover from an earlier refactor — `_dict_to_tool_definition` has nothing to do with dead code verification.
- `get_triage_exploration_tool_definitions()` (L1151–1158) returns 4 tools: 3 read-only retrieval tools (READ_FILE, GREP, LIST_DIR) plus the terminal verdict tool, enabling multi-turn exploration LLM sessions.
- All `input_schema` values follow Anthropic's tool use JSON Schema format (not OpenAI's `parameters` key).

## Dependencies
- `typing.Any` (L3) — used for `dict[str, Any]` type hint in `_dict_to_tool_definition`
- `.llm.types.ToolDefinition` (L5) — dataclass/namedtuple with `name`, `description`, `input_schema` fields (cross-file)