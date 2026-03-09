"""Orphaned file detection via purpose graph and LLM verification."""

import asyncio
import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .async_utils import gather_with_buffer
from .config import Config, SHADOW_DIR
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult, load_shadow_content
from .llm.base import LLMProvider
from .llm.runtime import create_runtime
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter
from .symbols import load_all_symbols, load_file_roles
from .tools import (
    get_identify_entry_points_tool_definitions,
    get_identify_relationships_tool_definitions,
    get_verify_orphan_files_tool_definitions,
)



@dataclass
class OrphanCandidate:
    """A file that may be orphaned."""

    source_path: str
    purpose: str
    topics: list[str]
    file_role: str
    public_surface: list[str] = field(default_factory=list)


@dataclass
class OrphanVerification:
    """Result of verifying whether a file is orphaned."""

    source_path: str
    is_orphaned: bool
    confidence: float
    reason: str
    remediation: str


# --- Phase 1: Import edges (deterministic, pure Python) ---

def _build_import_edges(all_symbols: dict[str, list[dict]], config: Config) -> dict[str, set[str]]:
    """Build adjacency from symbol cross-references.

    For each public symbol defined in file A, if file B references that symbol name,
    add a bidirectional edge A↔B. Returns {file: {connected_files}}.
    """
    adjacency: dict[str, set[str]] = {}

    # Collect all public symbol names and their defining files
    symbol_to_files: dict[str, list[str]] = {}
    all_symbol_names: set[str] = set()

    for source_path, symbols in all_symbols.items():
        source_norm = source_path.replace("\\", "/")
        adjacency.setdefault(source_norm, set())
        for sym in symbols:
            name = sym["name"]
            all_symbol_names.add(name)
            symbol_to_files.setdefault(name, []).append(source_norm)

    if not all_symbol_names:
        return adjacency

    # Build regex for all symbol names
    sorted_names = sorted(all_symbol_names, key=len, reverse=True)
    escaped = [re.escape(n) for n in sorted_names]
    pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    # Scan all files with symbols data for cross-references
    for source_path in all_symbols:
        source_norm = source_path.replace("\\", "/")
        full_path = config.root_path / source_path
        try:
            content = full_path.read_text(errors="ignore")
        except OSError:
            continue

        found_names: set[str] = set()
        for m in pattern.finditer(content):
            found_names.add(m.group(1))

        # For each found symbol, add edges to the defining file(s)
        for name in found_names:
            for defining_file in symbol_to_files.get(name, []):
                if defining_file != source_norm:
                    adjacency.setdefault(source_norm, set()).add(defining_file)
                    adjacency.setdefault(defining_file, set()).add(source_norm)

    return adjacency


# --- Phase 2: Entry point identification (Haiku) ---

_ENTRY_POINTS_SYSTEM_PROMPT = """You are identifying entry points in a software project.

An entry point is a file that is invoked directly rather than only imported:
- CLI scripts, main modules (__main__.py, manage.py)
- Test files (test_*.py, *_test.py, conftest.py)
- Package __init__.py files
- Framework entry points (app.py, wsgi.py, asgi.py)
- Configuration that's loaded by tools (setup.py, setup.cfg processing)
- Build/task scripts

Use the file_role hint but make your own judgment. Provide a verdict for EVERY file."""


async def _identify_entry_points_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    signatures: list[dict],
    config: Config,
) -> set[str]:
    """Haiku batch call to identify entry points from file signatures."""
    if not signatures:
        return set()

    entry_points: set[str] = set()

    # Batch up to 100 signatures per call
    for i in range(0, len(signatures), 100):
        batch = signatures[i:i + 100]

        lines = ["Identify which of these files are entry points:\n"]
        for sig in batch:
            lines.append(
                f"- `{sig['path']}` (role: {sig.get('file_role', 'unknown')}) — "
                f"{sig.get('purpose', 'no purpose')}"
            )

        expected = {sig["path"] for sig in batch}
        lines.append(f"\nProvide a verdict for EVERY file: {', '.join(f'`{p}`' for p in sorted(expected))}")

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "identify_entry_points":
                return []
            eps = tool_input.get("entry_points", [])
            got = {e.get("source_path") for e in eps}
            missing = expected - got
            return [f"Missing verdict for '{p}'" for p in sorted(missing)]

        result = await provider.complete(
            messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
            system=_ENTRY_POINTS_SYSTEM_PROMPT,
            options=CompletionOptions(
                model=config.model_for("small"),
                max_tokens=max(1024, len(batch) * 60),
                reservation_key="junk_orphan.identify_entry_points",
                tools=get_identify_entry_points_tool_definitions(),
                tool_choice={"type": "tool", "name": "identify_entry_points"},
                tool_input_validators=[check_completeness],
            ),
        )

        for tc in result.tool_calls:
            if tc.name == "identify_entry_points":
                for ep in tc.input.get("entry_points", []):
                    if ep.get("is_entry_point"):
                        entry_points.add(ep["source_path"])

    return entry_points


def _identify_entry_points_heuristic(signatures: list[dict]) -> set[str]:
    """Fallback: identify entry points using file_role hints only."""
    entry_points: set[str] = set()
    for sig in signatures:
        role = sig.get("file_role", "")
        path = sig["path"]
        name = Path(path).name

        if role in ("entry", "test"):
            entry_points.add(path)
        elif name == "__init__.py":
            entry_points.add(path)
        elif name in ("__main__.py", "manage.py", "setup.py", "conftest.py"):
            entry_points.add(path)
        elif name.startswith("test_") or name.endswith("_test.py"):
            entry_points.add(path)

    return entry_points


# --- Phase 3: Semantic relationship edges (Haiku) ---

_RELATIONSHIPS_SYSTEM_PROMPT = """You are identifying semantic relationships between source files.

You are given:
1. **disconnected**: Files not reachable from any entry point via import edges
2. **connected**: Files that ARE reachable

For each disconnected file, determine if it relates to any connected file based on
their purposes and topics. Only report confident relationships — it's OK to leave
disconnected files without a match (they may genuinely be orphaned)."""


async def _identify_relationships_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    disconnected: list[dict],
    connected: list[dict],
    config: Config,
) -> list[tuple[str, str]]:
    """Haiku identifies semantic relationships for disconnected files."""
    if not disconnected or not connected:
        return []

    relationships: list[tuple[str, str]] = []

    # Batch disconnected files, include full connected list as context
    # Limit connected context to avoid token overflow
    connected_summary = connected[:200]

    for i in range(0, len(disconnected), 50):
        batch = disconnected[i:i + 50]

        lines = ["## Disconnected files (not reachable via imports)\n"]
        for d in batch:
            lines.append(f"- `{d['path']}` — {d.get('purpose', 'unknown')} (topics: {d.get('topics', [])})")

        lines.append("\n## Connected files (reachable via imports)\n")
        for c in connected_summary:
            lines.append(f"- `{c['path']}` — {c.get('purpose', 'unknown')} (topics: {c.get('topics', [])})")

        lines.append("\nIdentify semantic relationships between disconnected and connected files.")

        result = await provider.complete(
            messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
            system=_RELATIONSHIPS_SYSTEM_PROMPT,
            options=CompletionOptions(
                model=config.model_for("small"),
                max_tokens=max(1024, len(batch) * 80),
                reservation_key="junk_orphan.identify_relationships",
                tools=get_identify_relationships_tool_definitions(),
                tool_choice={"type": "tool", "name": "identify_relationships"},
            ),
        )

        for tc in result.tool_calls:
            if tc.name == "identify_relationships":
                for rel in tc.input.get("relationships", []):
                    src = rel.get("source_path", "")
                    tgt = rel.get("related_to", "")
                    if src and tgt:
                        relationships.append((src, tgt))

    return relationships


# --- Phase 4: BFS orphan detection ---

def find_orphans(adjacency: dict[str, set[str]], entry_points: set[str]) -> list[str]:
    """BFS from entry points through adjacency. Unreachable nodes = orphan candidates."""
    all_nodes = set(adjacency.keys())
    visited: set[str] = set()
    queue: deque[str] = deque()

    # Seed with entry points
    for ep in entry_points:
        if ep in all_nodes:
            visited.add(ep)
            queue.append(ep)

    # BFS
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return sorted(all_nodes - visited)


# --- Phase 5: Sonnet orphan verification ---

_VERIFY_ORPHANS_SYSTEM_PROMPT = """You are verifying whether source files are truly orphaned (unreachable and unused).

Each file listed is not reachable via import edges from any entry point, and has no
detected semantic relationship to the rest of the project. But some may still be alive:
- Plugin/extension files loaded dynamically
- Convention-based files (migrations, fixtures, templates)
- Files referenced in configuration or CI/CD
- Script files invoked from command line

Set is_orphaned=True only if you're confident the file has no alive pathway.
Provide a verdict for EVERY file listed."""


async def _verify_orphans_batch_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    orphans: list[OrphanCandidate],
    shadow_contents: dict[str, str],
) -> tuple[list[OrphanVerification], int, int]:
    """Sonnet verification of orphan candidates.

    Returns (verifications, input_tokens, output_tokens).
    """
    user_parts: list[str] = []

    user_parts.append("## Orphan candidate files\n")
    for o in orphans:
        user_parts.append(
            f"### `{o.source_path}` (role: {o.file_role})\n"
            f"Purpose: {o.purpose}\n"
            f"Topics: {o.topics}\n"
        )
        shadow = shadow_contents.get(o.source_path, "")
        if shadow:
            user_parts.append(f"Shadow doc:\n{shadow[:3000]}\n")

    names_list = ", ".join(f"`{o.source_path}`" for o in orphans)
    user_parts.append(
        f"Provide a verdict for EVERY file listed ({names_list}) "
        "using the verify_orphan_files tool."
    )

    expected = {o.source_path for o in orphans}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_orphan_files":
            return []
        verdicts = tool_input.get("verdicts", [])
        got = {v.get("source_path") for v in verdicts}
        missing = expected - got
        return [f"Missing verdict for '{p}'" for p in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_VERIFY_ORPHANS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(1024, len(orphans) * 200),
            reservation_key="junk_orphan.verify",
            tools=get_verify_orphan_files_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_orphan_files"},
            tool_input_validators=[check_completeness],
        ),
    )

    verifications: list[OrphanVerification] = []
    for tc in result.tool_calls:
        if tc.name == "verify_orphan_files":
            for v in tc.input.get("verdicts", []):
                path = v.get("source_path", "")
                if path in expected:
                    verifications.append(OrphanVerification(
                        source_path=path,
                        is_orphaned=v.get("is_orphaned", False),
                        confidence=v.get("confidence", 0.5),
                        reason=v.get("reason", ""),
                        remediation=v.get("remediation", ""),
                    ))

    if not verifications:
        raise RuntimeError(
            f"LLM did not return verdicts for orphan files: "
            f"{[o.source_path for o in orphans]}"
        )

    return verifications, result.input_tokens, result.output_tokens


# --- Signature loading ---

def _load_signatures(config: Config) -> list[dict]:
    """Load all file signatures from .osoji/signatures/."""
    sigs: list[dict] = []
    sig_dir = config.root_path / SHADOW_DIR / "signatures"
    if not sig_dir.exists():
        return sigs

    for sig_file in sig_dir.rglob("*.signature.json"):
        if sig_file.name == "_directory.signature.json":
            continue
        try:
            data = json.loads(sig_file.read_text(encoding="utf-8"))
            path = data.get("path", "")
            if path:
                sigs.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    return sigs


# --- Full pipeline ---

async def detect_orphaned_files_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[OrphanVerification]:
    """Detect orphaned source files using a purpose graph.

    Pipeline:
    1. Build import edges (pure Python symbol cross-references)
    2. Identify entry points (Haiku)
    3. BFS from entry points → find disconnected files
    4. Identify semantic relationships for disconnected files (Haiku)
    5. BFS again with semantic edges → find orphan candidates
    6. Verify orphans (Sonnet)
    """
    # Load data sources
    all_symbols = load_all_symbols(config)
    file_roles = load_file_roles(config)
    signatures = _load_signatures(config)

    if not all_symbols:
        print("  [skip] No symbols data found.", flush=True)
        return []

    sig_by_path = {s["path"]: s for s in signatures}

    # Phase 1: Import edges
    adjacency = _build_import_edges(all_symbols, config)
    all_files = set(adjacency.keys())
    print(f"  Built import graph: {len(all_files)} files, {sum(len(v) for v in adjacency.values()) // 2} edges", flush=True)

    if not all_files:
        return []

    # Build signatures for all files (for Haiku calls)
    all_sigs: list[dict] = []
    for fpath in sorted(all_files):
        sig = sig_by_path.get(fpath, {})
        all_sigs.append({
            "path": fpath,
            "file_role": file_roles.get(fpath, "unknown"),
            "purpose": sig.get("purpose", ""),
            "topics": sig.get("topics", []),
            "public_surface": sig.get("public_surface", []),
        })

    # Phase 2: Identify entry points (Haiku with heuristic fallback)
    try:
        entry_points = await _identify_entry_points_async(
            provider, rate_limiter, all_sigs, config,
        )
        print(f"  Haiku identified {len(entry_points)} entry point(s)", flush=True)
    except Exception as e:
        print(f"  [warn] Haiku entry point identification failed, using heuristics: {e}", flush=True)
        entry_points = _identify_entry_points_heuristic(all_sigs)
        print(f"  Heuristic identified {len(entry_points)} entry point(s)", flush=True)

    if not entry_points:
        print("  [warn] No entry points identified, skipping orphan detection.", flush=True)
        return []

    # Phase 3: First BFS
    orphan_candidates_1 = find_orphans(adjacency, entry_points)
    print(f"  After import-edge BFS: {len(orphan_candidates_1)} disconnected file(s)", flush=True)

    if not orphan_candidates_1:
        return []

    # Phase 4: Semantic relationships for disconnected files (Haiku)
    disconnected_sigs = [s for s in all_sigs if s["path"] in set(orphan_candidates_1)]
    connected_sigs = [s for s in all_sigs if s["path"] not in set(orphan_candidates_1)]

    try:
        relationships = await _identify_relationships_async(
            provider, rate_limiter, disconnected_sigs, connected_sigs, config,
        )
        # Add semantic edges to adjacency
        for src, tgt in relationships:
            adjacency.setdefault(src, set()).add(tgt)
            adjacency.setdefault(tgt, set()).add(src)
        print(f"  Haiku identified {len(relationships)} semantic relationship(s)", flush=True)
    except Exception as e:
        print(f"  [warn] Haiku relationship identification failed: {e}", flush=True)
        relationships = []

    # Phase 5: Second BFS with semantic edges
    if relationships:
        orphan_candidates_2 = find_orphans(adjacency, entry_points)
        print(f"  After semantic-edge BFS: {len(orphan_candidates_2)} orphan candidate(s)", flush=True)
    else:
        orphan_candidates_2 = orphan_candidates_1

    if not orphan_candidates_2:
        return []

    # Build OrphanCandidate objects
    orphans: list[OrphanCandidate] = []
    for fpath in orphan_candidates_2:
        sig = sig_by_path.get(fpath, {})
        orphans.append(OrphanCandidate(
            source_path=fpath,
            purpose=sig.get("purpose", ""),
            topics=sig.get("topics", []),
            file_role=file_roles.get(fpath, "unknown"),
            public_surface=sig.get("public_surface", []),
        ))

    # Pre-load shadow docs
    shadow_contents: dict[str, str] = {}
    for o in orphans:
        shadow_contents[o.source_path] = load_shadow_content(config, o.source_path)

    # Phase 6: Sonnet verification (batch up to 10 per call)
    results: list[OrphanVerification] = []
    completed = 0
    total_batches = (len(orphans) + 9) // 10
    lock = asyncio.Lock()

    async def process_batch(batch: list[OrphanCandidate]) -> list[OrphanVerification]:
        nonlocal completed

        try:
            verifications, _in_tok, _out_tok = await _verify_orphans_batch_async(
                provider, rate_limiter, config, batch, shadow_contents,
            )

            async with lock:
                completed += 1
                dead_count = sum(1 for v in verifications if v.is_orphaned)
                for v in verifications:
                    if v.is_orphaned:
                        results.append(v)
                if on_progress:
                    on_progress(
                        completed, total_batches,
                        Path(batch[0].source_path),
                        f"{dead_count} orphaned",
                    )
            return verifications
        except Exception as e:
            async with lock:
                completed += 1
                if on_progress:
                    on_progress(
                        completed, total_batches,
                        Path(batch[0].source_path), "error",
                    )
            print(f"  [error] orphan verification: {e}", flush=True)
            return []

    batches = [orphans[i:i + 10] for i in range(0, len(orphans), 10)]
    await gather_with_buffer([lambda batch=batch: process_batch(batch) for batch in batches])

    return results


class OrphanedFilesAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects orphaned source files with no reachable purpose."""

    @property
    def name(self) -> str:
        return "orphaned_files"

    @property
    def description(self) -> str:
        return "Detect orphaned source files with no reachable purpose"

    @property
    def cli_flag(self) -> str:
        return "orphaned-files"

    def analyze(self, config, on_progress=None, rate_limiter=None):
        """Sync wrapper — requires symbols data."""
        symbols_dir = config.root_path / SHADOW_DIR / "symbols"
        if not symbols_dir.exists():
            print("  [skip] No symbols data found. Run 'osoji shadow .' first.", flush=True)
            return JunkAnalysisResult(findings=[], total_candidates=0, analyzer_name=self.name)

        async def _run() -> JunkAnalysisResult:
            logging_provider, rl = create_runtime(config, rate_limiter=rate_limiter)
            try:
                return await self.analyze_async(
                    logging_provider, rl, config, on_progress
                )
            finally:
                await logging_provider.close()

        return asyncio.run(_run())

    async def analyze_async(self, provider, rate_limiter, config, on_progress=None):
        results = await detect_orphaned_files_async(provider, rate_limiter, config, on_progress)
        findings = [
            JunkFinding(
                source_path=v.source_path,
                name=Path(v.source_path).name,
                kind="file",
                category="orphaned_file",
                line_start=1,
                line_end=None,
                confidence=v.confidence,
                reason=v.reason,
                remediation=v.remediation,
                original_purpose=f"file `{v.source_path}`",
            )
            for v in results if v.is_orphaned
        ]
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(results),
            analyzer_name=self.name,
        )
