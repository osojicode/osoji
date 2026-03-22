"""Documentation prompts: concept-centric coverage and writing prompt generation.

5-stage pipeline:
  Stage 0:   Metadata loading (topic signatures, file roles, fan-in)
  Stage 1+2: Concept inventory + appropriateness (single LLM call)
  Stage 3:   Coverage mapping (pure Python)
  Stage 4:   Gap analysis + writing prompt generation (LLM call)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Config, SHADOW_DIR
from .facts import FactsDB
from .junk import load_shadow_content
from .llm.base import LLMProvider
from .llm.runtime import create_runtime
from .llm.types import CompletionOptions, Message, MessageRole
from .rate_limiter import RateLimiter
from .scorecard import Scorecard
from .symbols import load_all_symbols, load_file_roles
from .tools import (
    get_concept_inventory_tool_definitions,
    get_writing_prompts_tool_definitions,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Concept:
    """A codebase-level concept, clustered from file-level topic_signatures."""

    concept_id: str
    concept_name: str
    concept_description: str
    source_files: list[str]
    concept_role: str
    appropriate_types: list[str]
    appropriateness_rationale: str
    # Populated in Stage 3 (coverage mapping)
    existing_coverage: list[dict] = field(default_factory=list)
    missing_types: list[str] = field(default_factory=list)
    coverage_status: str = "undocumented"
    # Priority (populated in Stage 4)
    priority: str = "low"
    priority_score: float = 0.0
    priority_signals: list[str] = field(default_factory=list)
    # Metadata
    fan_in: int = 0
    public_count: int = 0
    cluster_id: str | None = None


@dataclass
class WritingPrompt:
    """A self-contained writing prompt for one documentation gap."""

    prompt_id: str
    target_concepts: list[str]
    diataxis_type: str
    priority: str
    prompt_text: str
    shadow_doc_excerpts: list[dict] = field(default_factory=list)
    related_docs: list[str] = field(default_factory=list)
    scope_constraints: str = ""
    output_guidance: dict = field(default_factory=dict)
    cluster_id: str | None = None


@dataclass
class DocPromptsResult:
    """Complete output of the doc-prompts phase."""

    concepts: list[Concept]
    writing_prompts: list[WritingPrompt]
    total_concepts: int = 0
    fully_documented: int = 0
    partially_documented: int = 0
    undocumented: int = 0
    coverage_by_type: dict[str, dict] = field(default_factory=dict)
    total_gaps: int = 0
    total_prompts: int = 0


# ---------------------------------------------------------------------------
# Stage 0: Metadata loading
# ---------------------------------------------------------------------------

@dataclass
class _FileMetadata:
    """Per-file metadata for concept inventory input."""

    path: str
    purpose: str
    topics: list[str]
    file_role: str
    public_count: int
    fan_in: int


def _load_file_metadata(config: Config) -> list[_FileMetadata]:
    """Load topic_signatures, file_roles, fan-in, public_count for all source files."""
    file_roles = load_file_roles(config)
    all_symbols = load_all_symbols(config)

    # Fan-in from FactsDB
    facts_dir = config.root_path / SHADOW_DIR / "facts"
    fan_in_map: dict[str, int] = {}
    if facts_dir.exists():
        try:
            facts_db = FactsDB(config)
            for path in file_roles:
                fan_in_map[path] = len(facts_db.importers_of(path))
        except Exception:
            pass

    # Load signatures
    sig_dir = config.root_path / SHADOW_DIR / "signatures"
    signatures: dict[str, dict] = {}
    if sig_dir.exists():
        for sig_file in sig_dir.rglob("*.signature.json"):
            if sig_file.name == "_directory.signature.json":
                continue
            try:
                data = json.loads(sig_file.read_text(encoding="utf-8"))
                path = data.get("path", "")
                if path:
                    signatures[path] = data
            except (json.JSONDecodeError, OSError):
                continue

    result: list[_FileMetadata] = []
    for path, role in file_roles.items():
        sig = signatures.get(path, {})
        public_count = sum(
            1 for s in all_symbols.get(path, [])
            if s.get("visibility") == "public"
        )
        result.append(_FileMetadata(
            path=path,
            purpose=sig.get("purpose", ""),
            topics=sig.get("topics", []),
            file_role=role,
            public_count=public_count,
            fan_in=fan_in_map.get(path, 0),
        ))

    return result


# ---------------------------------------------------------------------------
# Stage 1+2: Concept inventory + appropriateness (single LLM call)
# ---------------------------------------------------------------------------

_CONCEPT_INVENTORY_SYSTEM_PROMPT = """\
You are a documentation architect analyzing a codebase to build a concept inventory.

Your task: consolidate file-level topic summaries into a codebase-level concept \
inventory. Each concept should represent a coherent, documentable unit — roughly \
what you'd see as a chapter heading in a developer guide.

CLUSTERING GUIDELINES:
- Merge related file-level topics into higher-level concepts when files collaborate \
on a single capability (e.g., breakpoints.ts + conditions.ts + hit_counts.ts → \
"Breakpoint Lifecycle")
- Keep concepts separate when files serve genuinely distinct purposes, even if \
they're in the same directory
- Target 15-25 concepts for a medium-sized project. Better to have well-defined \
concepts than granular ones that mirror the file list
- Every source file must belong to at least one concept. Files may belong to \
multiple concepts if they serve multiple concerns.

CONCEPT ROLES:
For each concept, classify its primary role. This determines what documentation \
types are appropriate:
- public_api: Exported functions, classes, or interfaces consumed by external users
- cli_command: Command-line interface entry points
- configuration: Config loading, env vars, settings management
- architectural_pattern: Design patterns, cross-cutting concerns, system structure
- internal_utility: Private helpers, shared formatters, internal plumbing
- integration_point: External system connectors (APIs, databases, file I/O)
- data_model: Core data structures, schemas, type definitions
- error_handling: Error types, recovery strategies, validation
- testing_infrastructure: Test utilities, fixtures, helpers (NOT the tests themselves)

APPROPRIATE DOCUMENTATION TYPES:
For each concept, determine which Diataxis types are genuinely useful:
- public_api → reference + tutorial + how-to
- cli_command → reference + how-to
- configuration → reference + how-to
- architectural_pattern → explanatory + reference
- internal_utility → reference only
- integration_point → how-to + reference
- data_model → reference (+ explanatory if complex)
- error_handling → how-to + reference
- testing_infrastructure → how-to + reference

You may override these defaults with justification. A complex internal utility \
may warrant an explanatory doc. A trivial public API may need only reference.

Use the provided metadata (file_role, public_count, fan_in) as signals, but \
make your own judgment from the topic signatures and file purposes."""


def _format_file_listing(metadata: list[_FileMetadata]) -> str:
    """Format file metadata into the user message for concept inventory."""
    lines = ["Source files with metadata:\n"]
    for m in metadata:
        lines.append("---")
        lines.append(f"path: {m.path}")
        lines.append(f"purpose: {m.purpose}")
        lines.append(f"topics: {m.topics}")
        lines.append(f"file_role: {m.file_role}")
        lines.append(f"public_count: {m.public_count}")
        lines.append(f"fan_in: {m.fan_in}")
    return "\n".join(lines)


async def _build_concept_inventory_async(
    provider: LLMProvider,
    config: Config,
    metadata: list[_FileMetadata],
) -> list[Concept]:
    """Single LLM call to build concept inventory with appropriateness."""
    if not metadata:
        return []

    user_message = _format_file_listing(metadata)

    # Build fan-in and public_count lookup for post-processing
    fan_in_map = {m.path: m.fan_in for m in metadata}
    public_count_map = {m.path: m.public_count for m in metadata}

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_message)],
        system=_CONCEPT_INVENTORY_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(4096, len(metadata) * 200),
            reservation_key="doc_prompts.concept_inventory",
            tools=get_concept_inventory_tool_definitions(),
            tool_choice={"type": "tool", "name": "build_concept_inventory"},
        ),
    )

    concepts: list[Concept] = []
    for tc in result.tool_calls:
        if tc.name == "build_concept_inventory":
            for c in tc.input.get("concepts", []):
                source_files = c.get("source_files", [])
                concept = Concept(
                    concept_id=c.get("concept_id", ""),
                    concept_name=c.get("concept_name", ""),
                    concept_description=c.get("concept_description", ""),
                    source_files=source_files,
                    concept_role=c.get("concept_role", "internal_utility"),
                    appropriate_types=c.get("appropriate_doc_types", []),
                    appropriateness_rationale=c.get("appropriateness_rationale", ""),
                    fan_in=sum(fan_in_map.get(f, 0) for f in source_files),
                    public_count=sum(public_count_map.get(f, 0) for f in source_files),
                )
                concepts.append(concept)

    return concepts


# ---------------------------------------------------------------------------
# Stage 3: Coverage mapping (pure Python)
# ---------------------------------------------------------------------------

def _map_coverage(concepts: list[Concept], scorecard: Scorecard) -> None:
    """Populate existing_coverage, missing_types, coverage_status on each concept."""
    source_to_docs: dict[str, list[dict]] = {}
    for entry in scorecard.coverage_entries:
        source_to_docs[entry.source_path] = entry.covering_docs

    for concept in concepts:
        seen: set[tuple[str, str]] = set()
        for src in concept.source_files:
            for doc in source_to_docs.get(src, []):
                key = (doc["path"], doc["classification"])
                if key not in seen:
                    seen.add(key)
                    concept.existing_coverage.append({
                        "doc_path": doc["path"],
                        "diataxis_type": doc["classification"],
                    })

        existing_types = {d["diataxis_type"] for d in concept.existing_coverage}
        concept.missing_types = [
            t for t in concept.appropriate_types if t not in existing_types
        ]
        if not concept.missing_types:
            concept.coverage_status = "fully_documented"
        elif existing_types:
            concept.coverage_status = "partially_documented"
        else:
            concept.coverage_status = "undocumented"


def _compute_coverage_summary(
    concepts: list[Concept],
) -> dict[str, dict]:
    """Aggregate concept coverage by Diataxis type."""
    type_needed: dict[str, int] = {}
    type_covered: dict[str, int] = {}

    for concept in concepts:
        for t in concept.appropriate_types:
            type_needed[t] = type_needed.get(t, 0) + 1
        existing_types = {d["diataxis_type"] for d in concept.existing_coverage}
        for t in concept.appropriate_types:
            if t in existing_types:
                type_covered[t] = type_covered.get(t, 0) + 1

    result: dict[str, dict] = {}
    for t in type_needed:
        result[t] = {
            "needed": type_needed[t],
            "covered": type_covered.get(t, 0),
        }
    return result


# ---------------------------------------------------------------------------
# Stage 4: Priority scoring + clustering + writing prompts
# ---------------------------------------------------------------------------

def _compute_priority(concept: Concept) -> None:
    """Compute priority score and label from concept signals."""
    score = 0.0
    signals: list[str] = []

    # Role-based scoring
    if concept.concept_role in ("public_api", "cli_command"):
        score += 3
        signals.append(f"user-facing ({concept.concept_role})")
    elif concept.concept_role in ("configuration", "integration_point"):
        score += 2
        signals.append(f"operational ({concept.concept_role})")
    elif concept.concept_role in ("architectural_pattern", "data_model"):
        score += 1
        signals.append(f"structural ({concept.concept_role})")

    # Fan-in scoring
    if concept.fan_in >= 5:
        score += 3
        signals.append(f"high fan-in ({concept.fan_in} dependents)")
    elif concept.fan_in >= 2:
        score += 1
        signals.append(f"moderate fan-in ({concept.fan_in} dependents)")

    # Public surface scoring
    if concept.public_count > 0:
        score += 2
        signals.append(f"exported public API ({concept.public_count} symbols)")

    # Coverage gap scoring
    if concept.coverage_status == "undocumented":
        score += 2
        signals.append("completely undocumented")

    # Testing infrastructure penalty
    if concept.concept_role == "testing_infrastructure":
        score -= 3
        signals.append("testing infrastructure (low priority)")

    concept.priority_score = score
    concept.priority_signals = signals

    if score >= 6:
        concept.priority = "high"
    elif score >= 3:
        concept.priority = "medium"
    else:
        concept.priority = "low"


def _cluster_for_prompts(concepts: list[Concept]) -> list[list[Concept]]:
    """Cluster underdocumented concepts by source file overlap for combined prompts."""
    underdoc = [c for c in concepts if c.missing_types]
    if not underdoc:
        return []

    # Build file-set for each concept
    file_sets = {c.concept_id: set(c.source_files) for c in underdoc}
    clustered: set[str] = set()
    clusters: list[list[Concept]] = []

    for i, c1 in enumerate(underdoc):
        if c1.concept_id in clustered:
            continue
        cluster = [c1]
        clustered.add(c1.concept_id)
        files1 = file_sets[c1.concept_id]
        for c2 in underdoc[i + 1:]:
            if c2.concept_id in clustered:
                continue
            files2 = file_sets[c2.concept_id]
            # Check >50% overlap
            if len(files1) > 0 and len(files2) > 0:
                overlap = len(files1 & files2)
                min_size = min(len(files1), len(files2))
                if overlap > min_size * 0.5:
                    # Also need a shared missing type
                    shared_missing = set(c1.missing_types) & set(c2.missing_types)
                    if shared_missing:
                        cluster.append(c2)
                        clustered.add(c2.concept_id)
        if len(cluster) >= 2:
            cluster_id = "-".join(sorted(c.concept_id for c in cluster))[:80]
            for c in cluster:
                c.cluster_id = cluster_id
            clusters.append(cluster)

    return clusters


# Writing prompt generation

_WRITING_PROMPTS_SYSTEM_PROMPT = """\
You are a technical writing strategist. Generate self-contained documentation \
writing prompts that another agent can execute without re-auditing the codebase.

For each documentation gap (concept × missing Diataxis type), produce a prompt \
that includes:
1. TASK: "Write a [type] covering [concept]" — clear, actionable
2. AUDIENCE: Who will read this doc, inferred from concept role
3. SCOPE: What to cover, what's explicitly out of bounds, what adjacent concepts \
to reference but not explain
4. QUALITY CRITERIA: What "done" looks like for this specific type and concept
5. CONSISTENCY: Reference existing related docs so the agent maintains consistency

For TUTORIALS: structure as a learning path with prerequisites, steps, and \
verification points. Focus on "follow along and learn."

For HOW-TO GUIDES: structure as goal-oriented steps. Focus on "accomplish this \
specific task." Assume the reader already understands the concepts.

For REFERENCE: structure as precise, complete, scannable information. Cover all \
public API surface, parameters, return values, error conditions.

For EXPLANATORY: structure as a discussion of why things work the way they do. \
Connect concepts, explain trade-offs, provide mental models.

When concepts are clustered, generate a single combined prompt covering all \
concepts in the cluster rather than separate prompts.

Output guidance should follow the project's existing doc structure and naming \
conventions."""


def _prepare_prompt_context(
    concept: Concept, config: Config,
) -> tuple[list[dict], list[str]]:
    """Load + trim shadow doc excerpts and gather related docs for a concept."""
    excerpts: list[dict] = []
    for src in concept.source_files[:5]:  # limit to avoid token explosion
        shadow = load_shadow_content(config, src)
        if shadow:
            excerpts.append({
                "source_file": src,
                "excerpt": shadow[:2000],
            })

    related_docs = [d["doc_path"] for d in concept.existing_coverage]
    return excerpts, related_docs


def _format_gaps_for_prompt(
    concepts: list[Concept],
    config: Config,
    clusters: list[list[Concept]],
) -> str:
    """Format all gaps into the user message for writing prompt generation."""
    lines: list[str] = []
    lines.append("Generate writing prompts for the following documentation gaps:\n")

    # Track which concepts are handled by clusters
    clustered_ids: set[str] = set()
    for cluster in clusters:
        for c in cluster:
            clustered_ids.add(c.concept_id)

    gap_index = 0

    # Clusters first
    for cluster in clusters:
        cluster_id = cluster[0].cluster_id
        lines.append(f"## Cluster: {cluster_id}")
        lines.append(f"Concepts in this cluster share overlapping source files.")
        shared_missing = set(cluster[0].missing_types)
        for c in cluster[1:]:
            shared_missing &= set(c.missing_types)

        for c in cluster:
            excerpts, related = _prepare_prompt_context(c, config)
            lines.append(f"\n### Concept: {c.concept_name} ({c.concept_id})")
            lines.append(f"Role: {c.concept_role}")
            lines.append(f"Description: {c.concept_description}")
            lines.append(f"Source files: {c.source_files}")
            lines.append(f"Missing types: {c.missing_types}")
            lines.append(f"Existing coverage: {[d['doc_path'] for d in c.existing_coverage]}")
            if excerpts:
                for ex in excerpts[:2]:
                    lines.append(f"\nShadow excerpt ({ex['source_file']}):")
                    lines.append(ex["excerpt"][:1000])
        lines.append(f"\nGenerate combined prompts for shared missing types: {sorted(shared_missing)}")
        lines.append("")
        gap_index += 1

    # Individual concepts not in clusters
    for concept in concepts:
        if concept.concept_id in clustered_ids:
            continue
        if not concept.missing_types:
            continue
        excerpts, related = _prepare_prompt_context(concept, config)
        lines.append(f"## Gap {gap_index}: {concept.concept_name} ({concept.concept_id})")
        lines.append(f"Role: {concept.concept_role}")
        lines.append(f"Description: {concept.concept_description}")
        lines.append(f"Source files: {concept.source_files}")
        lines.append(f"Missing types: {concept.missing_types}")
        lines.append(f"Existing coverage: {[d['doc_path'] for d in concept.existing_coverage]}")
        lines.append(f"Priority: {concept.priority} ({', '.join(concept.priority_signals)})")
        if excerpts:
            for ex in excerpts[:2]:
                lines.append(f"\nShadow excerpt ({ex['source_file']}):")
                lines.append(ex["excerpt"][:1000])
        if related:
            lines.append(f"Related existing docs: {related}")
        lines.append("")
        gap_index += 1

    lines.append(f"\nGenerate a writing prompt for EACH gap × missing type combination.")
    return "\n".join(lines)


async def _generate_writing_prompts_async(
    provider: LLMProvider,
    concepts: list[Concept],
    config: Config,
    clusters: list[list[Concept]],
) -> list[WritingPrompt]:
    """Generate writing prompts for all documentation gaps via single LLM call."""
    gaps = [c for c in concepts if c.missing_types]
    if not gaps:
        return []

    user_message = _format_gaps_for_prompt(concepts, config, clusters)

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_message)],
        system=_WRITING_PROMPTS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(4096, len(gaps) * 2000),
            reservation_key="doc_prompts.writing_prompts",
            tools=get_writing_prompts_tool_definitions(),
            tool_choice={"type": "tool", "name": "generate_writing_prompts"},
        ),
    )

    prompts: list[WritingPrompt] = []
    concept_map = {c.concept_id: c for c in concepts}

    for tc in result.tool_calls:
        if tc.name == "generate_writing_prompts":
            for p in tc.input.get("prompts", []):
                target_ids = p.get("target_concept_ids", [])
                # Look up priority from highest-priority target concept
                _PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
                priority = "low"
                for cid in target_ids:
                    c = concept_map.get(cid)
                    if c and _PRIORITY_RANK.get(c.priority, 0) > _PRIORITY_RANK.get(priority, 0):
                        priority = c.priority

                # Find shadow doc excerpts for target concepts
                excerpts: list[dict] = []
                related: list[str] = []
                for cid in target_ids:
                    c = concept_map.get(cid)
                    if c:
                        ex, rel = _prepare_prompt_context(c, config)
                        excerpts.extend(ex)
                        related.extend(rel)

                output_guidance = p.get("output_guidance", {})
                cluster_id = None
                if len(target_ids) > 1:
                    cluster_id = "-".join(sorted(target_ids))[:80]

                prompts.append(WritingPrompt(
                    prompt_id=p.get("prompt_id", ""),
                    target_concepts=target_ids,
                    diataxis_type=p.get("diataxis_type", ""),
                    priority=priority,
                    prompt_text=p.get("prompt_text", ""),
                    shadow_doc_excerpts=excerpts,
                    related_docs=list(set(related)),
                    scope_constraints=p.get("scope_constraints", ""),
                    output_guidance={
                        "filename": output_guidance.get("suggested_filename", ""),
                        "directory": output_guidance.get("suggested_directory", ""),
                    },
                    cluster_id=cluster_id,
                ))

    return prompts


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def build_doc_prompts_async(
    config: Config,
    scorecard: Scorecard,
    rate_limiter: RateLimiter | None = None,
) -> DocPromptsResult:
    """Run the full 4-stage doc-prompts pipeline.

    Stage 1+2: Concept inventory (LLM)
    Stage 3:   Coverage mapping (pure Python)
    Stage 4:   Gap analysis + prompts (LLM)
    """
    logging_provider, _ = create_runtime(config, rate_limiter=rate_limiter)

    try:
        # Stage 0: Load metadata
        metadata = _load_file_metadata(config)
        if not metadata:
            return DocPromptsResult(concepts=[], writing_prompts=[])

        # Stage 1+2: Concept inventory
        concepts = await _build_concept_inventory_async(
            logging_provider, config, metadata,
        )
        if not concepts:
            return DocPromptsResult(concepts=[], writing_prompts=[])

        # Stage 3: Coverage mapping
        _map_coverage(concepts, scorecard)

        # Stage 4a: Priority scoring
        for concept in concepts:
            _compute_priority(concept)

        # Stage 4b: Clustering
        clusters = _cluster_for_prompts(concepts)

        # Stage 4c: Writing prompt generation
        prompts = await _generate_writing_prompts_async(
            logging_provider, concepts, config, clusters,
        )
    finally:
        await logging_provider.close()

    # Build summary
    coverage_by_type = _compute_coverage_summary(concepts)
    fully_documented = sum(1 for c in concepts if c.coverage_status == "fully_documented")
    partially_documented = sum(1 for c in concepts if c.coverage_status == "partially_documented")
    undocumented = sum(1 for c in concepts if c.coverage_status == "undocumented")
    total_gaps = sum(len(c.missing_types) for c in concepts)

    return DocPromptsResult(
        concepts=concepts,
        writing_prompts=prompts,
        total_concepts=len(concepts),
        fully_documented=fully_documented,
        partially_documented=partially_documented,
        undocumented=undocumented,
        coverage_by_type=coverage_by_type,
        total_gaps=total_gaps,
        total_prompts=len(prompts),
    )
