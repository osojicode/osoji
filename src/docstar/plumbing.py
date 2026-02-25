"""Dead plumbing detection via obligation tracing.

Finds config fields that are defined, parsed, stored, and passed around — but never
reach an actuator that enforces their declared intent. For example, a `taskTimeoutMs`
field in a schema that is parsed from YAML and threaded through config objects but
never used to enforce a timeout.
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult, load_shadow_content
from .llm.base import LLMProvider
from .llm.factory import create_provider
from .llm.logging import LoggingProvider
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter, get_config_with_overrides
from .symbols import load_files_by_role
from .tools import get_extract_obligations_tool_definitions, get_verify_actuation_tool_definitions
from .walker import list_repo_files, _matches_ignore


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


@dataclass
class PlumbingVerification:
    """Result of verifying whether a config obligation is actuated."""

    source_path: str
    field_name: str
    schema_name: str
    line_start: int
    line_end: int | None
    is_actuated: bool
    confidence: float
    trace: str  # data flow description (or gap)
    remediation: str


@dataclass
class PlumbingResult:
    """Complete result from dead plumbing detection."""

    verifications: list[PlumbingVerification]  # only unactuated
    total_obligations: int  # total fields examined


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
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
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


# --- Phase B: Actuation Verification ---

_VERIFY_ACTUATION_SYSTEM_PROMPT = """You are tracing a config field from its schema definition through the codebase to determine
whether it is ever used to CAUSE its declared effect (actuation).

You are given:
1. The obligation: what the field promises to enforce
2. The schema's shadow doc showing the field definition
3. Shadow docs for ALL files that reference this field
4. Shadow docs for sibling fields from the same schema that ARE properly enforced (as positive counterexamples)

Your job: trace the data flow from schema → config loading → handoff → enforcement.

Key question: "Does any shadow doc describe this field being used to CAUSE the declared effect?
Or is it only stored, passed, and restructured?"

Actuation examples:
- setTimeout(callback, field) — actuation via timer
- if (turns >= field) break — actuation via loop guard
- axios({timeout: field}) — actuation via library that enforces it
- Passing as env var to a container whose shadow doc says it reads and enforces it — actuation

NOT actuation:
- Logging the value
- Storing in results/metrics
- Including in a config object that is only read by other config code
- Displaying in a UI

Use the verify_actuation tool with your judgment."""


async def verify_actuation_async(
    provider: LLMProvider,
    config: Config,
    obligation: ConfigObligation,
    schema_shadow: str,
    referencing_shadows: dict[str, str],
    sibling_shadows: dict[str, str],
) -> tuple[PlumbingVerification, int, int]:
    """Verify whether a single obligation is actuated.

    Returns (PlumbingVerification, input_tokens, output_tokens).
    """
    user_parts = []
    user_parts.append(f"## Obligation under analysis\n")
    user_parts.append(f"- **Field**: `{obligation.field_name}`")
    user_parts.append(f"- **Schema**: `{obligation.schema_name}`")
    user_parts.append(f"- **File**: `{obligation.source_path}`")
    user_parts.append(f"- **Line**: {obligation.line_start}"
                      + (f"-{obligation.line_end}" if obligation.line_end else ""))
    user_parts.append(f"- **Obligation**: {obligation.obligation}")
    user_parts.append(f"- **Expected actuation**: {obligation.expected_actuation}")
    user_parts.append("")

    # Schema shadow doc
    if schema_shadow:
        user_parts.append(f"## Schema shadow doc: `{obligation.source_path}`\n{schema_shadow}\n")

    # Referencing file shadows
    if referencing_shadows:
        user_parts.append(f"## Files referencing `{obligation.field_name}` ({len(referencing_shadows)} files)\n")
        for path, shadow in referencing_shadows.items():
            user_parts.append(f"### `{path}`\n{shadow}\n")

    # Sibling field shadows (positive counterexamples)
    if sibling_shadows:
        user_parts.append(f"## Sibling fields from same schema (for comparison)\n")
        for label, shadow in sibling_shadows.items():
            user_parts.append(f"### {label}\n{shadow}\n")

    user_parts.append("Trace this field and determine if it is actuated using the verify_actuation tool.")

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_VERIFY_ACTUATION_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model,
            max_tokens=1024,
            tools=get_verify_actuation_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_actuation"},
        ),
    )

    for tool_call in result.tool_calls:
        if tool_call.name == "verify_actuation":
            return (
                PlumbingVerification(
                    source_path=obligation.source_path,
                    field_name=obligation.field_name,
                    schema_name=obligation.schema_name,
                    line_start=obligation.line_start,
                    line_end=obligation.line_end,
                    is_actuated=tool_call.input["is_actuated"],
                    confidence=tool_call.input["confidence"],
                    trace=tool_call.input["trace"],
                    remediation=tool_call.input["remediation"],
                ),
                result.input_tokens,
                result.output_tokens,
            )

    raise RuntimeError(f"LLM did not call verify_actuation for {obligation.field_name}")


# --- Reference scanning (no LLM) ---

def _find_field_references(
    config: Config,
    field_name: str,
    defining_file: str,
    file_content_cache: dict[str, str] | None = None,
) -> list[str]:
    """Find all files referencing a field name (excluding the defining file).

    Returns list of relative source paths.
    When file_content_cache is provided, read_text results are cached
    so repeated calls don't re-read the same files.
    """
    all_paths, _ = list_repo_files(config)
    all_paths = list(all_paths)

    docstarignore = config.load_docstarignore()
    pattern = re.compile(r"\b" + re.escape(field_name) + r"\b")

    referencing: list[str] = []
    for path in all_paths:
        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)
        rel_str = str(relative).replace("\\", "/")

        if rel_str.startswith(".docstar"):
            continue
        if rel_str == defining_file:
            continue
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if docstarignore and _matches_ignore(relative, docstarignore):
            continue

        # Use cache when available to avoid redundant file reads
        if file_content_cache is not None and rel_str in file_content_cache:
            content = file_content_cache[rel_str]
        else:
            try:
                content = path.read_text(errors="ignore")
            except OSError:
                continue
            if file_content_cache is not None:
                file_content_cache[rel_str] = content

        if pattern.search(content):
            referencing.append(rel_str)

    return referencing


def _load_shadow_content(config: Config, relative_path: str) -> str:
    """Load shadow doc content for a relative source path."""
    return load_shadow_content(config, relative_path)


# --- Full pipeline ---

async def detect_dead_plumbing_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> PlumbingResult:
    """Detect unactuated config obligations across the project.

    Phase A: Extract obligations from schema files (Haiku)
    Phase B: Verify actuation for each obligation (Sonnet)

    Returns PlumbingResult with unactuated verifications and total obligation count.
    """
    # Step 1: Find schema files
    schema_files = load_files_by_role(config, "schema")
    if not schema_files:
        print("  [skip] No schema files found. Run 'docstar shadow . --force' to classify files.", flush=True)
        return PlumbingResult(verifications=[], total_obligations=0)

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

        shadow_content = _load_shadow_content(config, source_path)

        await rate_limiter.throttle()
        try:
            obligations, in_tok, out_tok = await extract_obligations_async(
                provider, config, source_path, source_content, shadow_content
            )
            rate_limiter.record_usage(input_tokens=in_tok, output_tokens=out_tok)
            return obligations
        except Exception as e:
            print(f"  [error] extracting obligations from {source_path}: {e}", flush=True)
            return []

    extraction_results = await asyncio.gather(*[extract_one(sp) for sp in schema_files])
    all_obligations: list[ConfigObligation] = []
    for obligations in extraction_results:
        all_obligations.extend(obligations)

    if not all_obligations:
        print("  No obligation-bearing fields found in schema files.", flush=True)
        return PlumbingResult(verifications=[], total_obligations=0)

    print(f"  Found {len(all_obligations)} obligation-bearing field(s)", flush=True)

    # Step 3: Verify actuation for each obligation (Phase B)
    results: list[PlumbingVerification] = []
    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed = 0
    total = len(all_obligations)
    lock = asyncio.Lock()

    # Group obligations by schema for sibling lookups
    obligations_by_schema: dict[str, list[ConfigObligation]] = {}
    for obl in all_obligations:
        key = f"{obl.source_path}:{obl.schema_name}"
        if key not in obligations_by_schema:
            obligations_by_schema[key] = []
        obligations_by_schema[key].append(obl)

    # Shared cache for file contents across all _find_field_references calls
    file_content_cache: dict[str, str] = {}

    async def verify_one(obligation: ConfigObligation) -> PlumbingVerification | None:
        nonlocal completed

        async with semaphore:
            # Find referencing files
            refs = _find_field_references(config, obligation.field_name, obligation.source_path, file_content_cache)

            # Load shadow docs for referencing files
            ref_shadows: dict[str, str] = {}
            for ref_path in refs:
                shadow = _load_shadow_content(config, ref_path)
                if shadow:
                    ref_shadows[ref_path] = shadow

            # Build sibling shadows (other obligations from same schema)
            schema_key = f"{obligation.source_path}:{obligation.schema_name}"
            siblings = obligations_by_schema.get(schema_key, [])
            sibling_shadows: dict[str, str] = {}
            for sibling in siblings:
                if sibling.field_name == obligation.field_name:
                    continue
                # Find sibling's referencing files and collect their shadows
                sib_refs = _find_field_references(config, sibling.field_name, obligation.source_path, file_content_cache)
                for sib_ref in sib_refs:
                    shadow = _load_shadow_content(config, sib_ref)
                    if shadow:
                        label = f"`{sibling.field_name}` in `{sib_ref}`"
                        sibling_shadows[label] = shadow

            schema_shadow = _load_shadow_content(config, obligation.source_path)

            await rate_limiter.throttle()
            try:
                verification, in_tok, out_tok = await verify_actuation_async(
                    provider, config, obligation,
                    schema_shadow, ref_shadows, sibling_shadows,
                )
                rate_limiter.record_usage(input_tokens=in_tok, output_tokens=out_tok)

                async with lock:
                    completed += 1
                    if not verification.is_actuated:
                        results.append(verification)
                    status = "ok" if verification.is_actuated else "unactuated"
                    if on_progress:
                        on_progress(completed, total, Path(obligation.source_path), status)

                return verification
            except Exception as e:
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, Path(obligation.source_path), "error")
                print(f"  [error] {obligation.source_path}:{obligation.field_name}: {e}", flush=True)
                return None

    tasks = [verify_one(obl) for obl in all_obligations]
    await asyncio.gather(*tasks)

    return PlumbingResult(verifications=results, total_obligations=len(all_obligations))


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

    async def analyze_async(self, provider, rate_limiter, config, on_progress=None):
        result = await detect_dead_plumbing_async(provider, rate_limiter, config, on_progress)
        findings = [
            JunkFinding(
                source_path=v.source_path,
                name=v.field_name,
                kind="config_field",
                category="unactuated_config",
                line_start=v.line_start,
                line_end=v.line_end,
                confidence=v.confidence,
                reason=v.trace,
                remediation=v.remediation,
                original_purpose=f"field `{v.field_name}` in `{v.schema_name}`",
                metadata={"schema_name": v.schema_name, "trace": v.trace},
            )
            for v in result.verifications if not v.is_actuated
        ]
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=result.total_obligations,
            analyzer_name=self.name,
        )
