"""Dead plumbing detection via obligation tracing.

Finds config fields that are defined, parsed, stored, and passed around — but never
reach an actuator that enforces their declared intent. For example, a `taskTimeoutMs`
field in a schema that is parsed from YAML and threaded through config objects but
never used to enforce a timeout.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .async_utils import gather_with_buffer
from .config import Config
from .evidence_builders import BuildContext, _scanner_meta
from .facts import FactsDB
from .findings import Finding
from .findings_adapter import finding_from_config_obligation
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult, load_shadow_content
from .junk_triage import build_junk_claims, decide_junk_claims
from .llm.base import LLMProvider
from .llm.budgets import input_budget_for_config
from .llm.types import Message, MessageRole, CompletionOptions
from .symbols import load_files_by_role
from .tools import get_extract_obligations_tool_definitions


@dataclass
class ConfigObligation:
    """A field in a schema that declares a behavioral obligation."""

    source_path: str  # file defining the schema
    field_name: str  # e.g., "taskTimeoutMs"
    schema_name: str  # e.g., "TrialSettingsSchema"
    line_start: int
    line_end: int | None
    obligation: str  # what the field promises
    expected_actuation: str  # what enforcement would look like
    evidence: str = ""  # direct quote from schema text grounding the obligation


# --- Phase A: Obligation Extraction ---

_EXTRACT_OBLIGATIONS_SYSTEM_PROMPT = """You are analyzing a schema file to find fields that declare behavioral obligations.

An "obligation-bearing" field is one whose name and context promise the system will enforce
a runtime behavior. Think: timeouts, rate limits, max retries, size limits, concurrency caps,
TTLs, deadlines.

NOT obligation-bearing:
- Identity fields: name, id, description, label, title
- Purely quantitative: count, total (unless "maxCount" or similar implies a limit)
- Data shape fields: type, kind, format, version
- Descriptive: status, state, result
- Position/metadata fields: line_start, line_end, line_number, offset, column, index
- LLM tool schema constraints: minimum, maximum, enum, range constraints on fields inside
  tool definitions for structured LLM output (e.g., Anthropic tool_use schemas). These
  constraints guide the LLM's output format, not application code — enforcement happens
  at the API layer, not in the application.

IMPORTANT: Only extract obligations that are TEXTUALLY STATED in the schema (in descriptions,
comments, or constraint declarations). Do NOT infer obligations from field names alone.
- Do NOT infer "line_end >= line_start" just because two fields sound like a range
- If a field has no description and no constraints, it has no obligation
- Bare type declarations like {"type": "integer"} alone are NOT obligations
- Do NOT invent constraints that are not written in the schema text

For each obligation-bearing field, describe:
1. What the field promises (obligation) — must be grounded in schema text
2. What enforcement code would look like (expected actuation pattern)

Use the extract_obligations tool with your findings."""


async def extract_obligations_async(
    provider: LLMProvider,
    config: Config,
    source_path: str,
    source_content: str,
    shadow_content: str,
) -> tuple[list[ConfigObligation], int, int]:
    """Extract obligation-bearing fields from a schema file.

    Returns (obligations, input_tokens, output_tokens).
    """
    user_parts = []
    user_parts.append(f"## Schema file: `{source_path}`\n")
    user_parts.append(f"```\n{source_content[:30000]}\n```\n")
    if shadow_content:
        user_parts.append(f"## Shadow doc for `{source_path}`\n{shadow_content}\n")
    user_parts.append("Identify all obligation-bearing fields using the extract_obligations tool.")

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_EXTRACT_OBLIGATIONS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("small"),
            max_tokens=2048,
            max_input_tokens=input_budget_for_config(config),
            reservation_key="plumbing.extract_obligations",
            tools=get_extract_obligations_tool_definitions(),
            tool_choice={"type": "tool", "name": "extract_obligations"},
        ),
    )

    obligations: list[ConfigObligation] = []
    for tool_call in result.tool_calls:
        if tool_call.name == "extract_obligations":
            for item in tool_call.input.get("obligations", []):
                obligations.append(ConfigObligation(
                    source_path=source_path,
                    field_name=item["field_name"],
                    schema_name=item.get("schema_name", ""),
                    line_start=item["line_start"],
                    line_end=item.get("line_end"),
                    obligation=item["obligation"],
                    expected_actuation=item["expected_actuation"],
                    evidence=item.get("evidence", ""),
                ))
            return obligations, result.input_tokens, result.output_tokens

    raise RuntimeError(f"LLM did not call extract_obligations for {source_path}")


# --- Full pipeline ---

async def detect_dead_plumbing_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> tuple[list[Finding], int]:
    """Detect unactuated config obligations through the unified pipeline.

    Phase A (proposal, retained): extract obligation-bearing fields from schema
    files. Each obligation becomes a reachability Finding whose claim is framed
    in enforcement terms; the Claim Builder assembles cross-file references and
    Triage judges actuation (a store/pass/log reference is a real use in the
    sweep sense but does not enforce — the unified rubric's unactuated-config
    clause makes that distinction).

    Returns ``(decided Findings — all verdicts; callers keep ``confirmed`` —,
    total obligations examined)``.
    """
    # Step 1: Find schema files
    schema_files = load_files_by_role(config, "schema")
    if not schema_files:
        print("  [skip] No schema files found. Run 'osoji shadow . --force' to classify files.", flush=True)
        return [], 0

    print(f"  Found {len(schema_files)} schema file(s)", flush=True)

    # Step 2: Extract obligations from each schema file (Phase A) — parallel
    async def extract_one(source_path: str) -> list[ConfigObligation]:
        src_file = config.root_path / source_path
        if not src_file.is_file():
            return []

        try:
            source_content = src_file.read_text(errors="ignore")
        except OSError:
            return []

        shadow_content = load_shadow_content(config, source_path)

        try:
            obligations, _in_tok, _out_tok = await extract_obligations_async(
                provider, config, source_path, source_content, shadow_content
            )
            return obligations
        except Exception as e:
            print(f"  [error] extracting obligations from {source_path}: {e}", flush=True)
            return []

    extraction_results = await gather_with_buffer(
        [lambda source_path=sp: extract_one(source_path) for sp in schema_files]
    )
    all_obligations: list[ConfigObligation] = []
    for obligations in extraction_results:
        all_obligations.extend(obligations)

    if not all_obligations:
        print("  No obligation-bearing fields found in schema files.", flush=True)
        return [], 0

    print(f"  Found {len(all_obligations)} obligation-bearing field(s)", flush=True)

    # Step 3: Build claims and decide actuation through unified Triage
    findings = [finding_from_config_obligation(o) for o in all_obligations]
    ctx = BuildContext(config, facts_db=FactsDB(config))
    claims = build_junk_claims(findings, ctx)
    decided, _in_tokens, _out_tokens = await decide_junk_claims(
        claims, config, provider, on_progress=on_progress
    )
    return decided, len(all_obligations)


class DeadPlumbingAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects unactuated config obligations."""

    @property
    def name(self) -> str:
        return "dead_plumbing"

    @property
    def description(self) -> str:
        return "Detect unactuated config obligations"

    @property
    def cli_flag(self) -> str:
        return "dead-plumbing"

    async def analyze_async(self, provider, config, on_progress=None):
        decided, total = await detect_dead_plumbing_async(provider, config, on_progress)
        findings = []
        for f in decided:
            if f.verdict != "confirmed":
                continue
            meta = _scanner_meta(f)
            field_name = meta.get("field_name", f.symbol or "")
            schema_name = meta.get("schema_name", "")
            findings.append(JunkFinding(
                source_path=f.path,
                name=field_name,
                kind="config_field",
                category="unactuated_config",
                line_start=f.line_start or 1,
                line_end=f.line_end,
                confidence=f.confidence if f.confidence is not None else 0.0,
                reason=f.triage_reasoning or "",
                remediation=f.suggested_fix or f"Add enforcement for `{field_name}`",
                original_purpose=f"field `{field_name}` in `{schema_name}`",
                confidence_source="llm_inferred",
                # trace drew on the deleted verify tool's separate `trace` field;
                # the unified verdict carries reasoning instead.
                metadata={"schema_name": schema_name, "trace": f.triage_reasoning or ""},
            ))
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=total,
            analyzer_name=self.name,
        )
