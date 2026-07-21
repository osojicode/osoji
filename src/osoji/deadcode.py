"""Cross-file dead code detection via public symbol reference scanning.

Propose-time is mechanical (AST fast path over FactsDB + grep reference scan);
verification is the unified Claim Builder + Triage pipeline (V1-5a, spec 0001
step 5). This module no longer owns an LLM prompt or tool schema.
"""

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .config import Config, SHADOW_DIR
from .evidence_builders import BuildContext, _scanner_meta
from .facts import FactsDB
from .findings import Finding
from .findings_adapter import finding_from_dead_code_candidate
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult
from .junk_triage import build_junk_claims, decide_junk_claims
from .llm.base import LLMProvider
from .symbols import load_all_symbols, load_file_roles
from .triage import Claim
from .walker import list_repo_files, _matches_ignore


@dataclass
class GrepHit:
    """A textual reference to a symbol found in another file."""

    file_path: str  # relative path where reference was found
    line_number: int
    context: str  # ±5 lines around the match


@dataclass
class DeadCodeCandidate:
    """A symbol that may be dead code."""

    source_path: str  # relative path to defining file
    name: str  # symbol name
    kind: str  # function/class/constant/variable
    line_start: int
    line_end: int | None
    ref_count: int  # number of external file references
    grep_hits: list[GrepHit] = field(default_factory=list)


def _merged_refs(name: str, file_refs: dict) -> dict[str, list[int]]:
    """Get file references for a symbol, merging qualified and bare name hits."""
    refs = dict(file_refs.get(name, {}))
    if "." in name:
        bare = name.rsplit(".", 1)[1]
        for f, lines in file_refs.get(bare, {}).items():
            if f in refs:
                refs[f] = list(set(refs[f]) | set(lines))
            else:
                refs[f] = lines
    return refs


def _extract_context(lines: list[str], line_number: int, radius: int = 5) -> str:
    """Extract ±radius lines of context around a match (1-indexed line_number)."""
    idx = line_number - 1  # convert to 0-indexed
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    context_lines = []
    for i in range(start, end):
        marker = ">>>" if i == idx else "   "
        context_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")
    return "\n".join(context_lines)


def _compute_transitive_liveness(
    symbols: list[tuple[str, int, int | None]],
    file_lines: list[str],
    has_external_refs: Callable[[str], bool],
) -> set[str]:
    """BFS within-file liveness propagation.

    Given a list of (name, line_start, line_end) symbols and the file's lines,
    build a within-file reference graph and propagate liveness from symbols
    where has_external_refs(name) is True.

    Returns set of symbol names that are transitively alive (have zero external
    refs themselves but are referenced by a symbol that does).
    """
    if len(symbols) < 2:
        return set()

    sym_names = {s[0] for s in symbols}
    sorted_names = sorted(sym_names, key=len, reverse=True)
    file_pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in sorted_names) + r")\b"
    )

    # Build within-file reference graph
    uses: dict[str, set[str]] = {s[0]: set() for s in symbols}
    for sym_name, line_start, line_end in symbols:
        start_idx = line_start - 1
        # +1 padding on line_end compensates for LLM-extracted line ranges
        # that are commonly 1 line short of the actual function body end.
        end_idx = (line_end + 1) if line_end else line_start
        for line_idx in range(start_idx, min(end_idx, len(file_lines))):
            for m in file_pattern.finditer(file_lines[line_idx]):
                referenced = m.group(1)
                if referenced != sym_name:
                    uses[sym_name].add(referenced)

    # Seeds: symbols with external refs
    alive: set[str] = set()
    for sym_name, _, _ in symbols:
        if has_external_refs(sym_name):
            alive.add(sym_name)

    # BFS propagation
    queue = list(alive)
    while queue:
        current = queue.pop()
        for referenced in uses.get(current, set()):
            if referenced not in alive:
                alive.add(referenced)
                queue.append(referenced)

    # Return only zero-ref symbols that became alive through transitivity
    return {name for name in alive if not has_external_refs(name)}


def scan_references(
    config: Config,
    exclude_files: set[str] | None = None,
    file_roles: dict[str, str] | None = None,
    facts_db: FactsDB | None = None,
) -> tuple[list[DeadCodeCandidate], list[DeadCodeCandidate]]:
    """Scan for symbols with zero or low external references.

    Args:
        config: Osoji configuration
        exclude_files: Optional set of source file paths whose symbols should
            be excluded from candidates (already handled by AST fast path).
        file_roles: Optional mapping of source path -> role (e.g. "test").
        facts_db: Optional FactsDB for exclude_from_dead_analysis lookups.

    Returns (zero_ref_candidates, low_ref_candidates).
    Pure Python, no LLM calls.
    """
    all_symbols = load_all_symbols(config)
    if not all_symbols:
        return [], []

    # Collect all unique symbol names
    symbol_names: set[str] = set()
    for symbols in all_symbols.values():
        for sym in symbols:
            symbol_names.add(sym["name"])
            # Also add bare method name for class-qualified symbols
            # (e.g. "Config.method_name" -> also add "method_name")
            # so case-insensitive instance refs like config.method_name match
            if "." in sym["name"]:
                bare = sym["name"].rsplit(".", 1)[1]
                if bare:
                    symbol_names.add(bare)

    if not symbol_names:
        return [], []

    # Build one compiled regex: \b(sym1|sym2|...)\b
    # Sort longest-first to avoid prefix-match issues in alternation
    sorted_names = sorted(symbol_names, key=len, reverse=True)
    escaped = [re.escape(name) for name in sorted_names]
    pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    # Get ALL repo files
    all_paths, _ = list_repo_files(config)
    all_paths = list(all_paths)

    osojiignore = config.load_osojiignore()

    # For each file, find which symbol names appear and at which lines
    # file_refs[symbol_name] = {relative_file_path: [line_numbers]}
    file_refs: dict[str, dict[str, list[int]]] = {name: {} for name in symbol_names}

    # Also cache file lines for context extraction
    file_lines_cache: dict[str, list[str]] = {}

    for path in all_paths:
        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)
        # Normalize to forward slashes
        rel_str = str(relative).replace("\\", "/")

        # Skip .osoji/
        if rel_str.startswith(SHADOW_DIR):
            continue

        # Skip ignore patterns
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if osojiignore and _matches_ignore(relative, osojiignore):
            continue
        if config.is_doc_candidate(relative):
            continue

        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue

        # Find all matches
        matches_in_file: dict[str, list[int]] = {}
        lines = content.split("\n")
        for line_idx, line in enumerate(lines):
            for m in pattern.finditer(line):
                name = m.group(1)
                if name not in matches_in_file:
                    matches_in_file[name] = []
                matches_in_file[name].append(line_idx + 1)  # 1-indexed

        for name, line_numbers in matches_in_file.items():
            file_refs[name][rel_str] = line_numbers

        # Cache lines if any symbols were found
        if matches_in_file:
            file_lines_cache[rel_str] = lines

    # For each symbol, count external files
    zero_ref: list[DeadCodeCandidate] = []
    low_ref: list[DeadCodeCandidate] = []

    # Build per-symbol external ref counts
    sym_ref_counts: dict[tuple[str, str], int] = {}  # (source_path, name) -> count
    sym_entries: list[tuple[str, dict]] = []  # (source_path, symbol_dict)

    for source_path, symbols in all_symbols.items():
        # Normalize source path
        source_norm = source_path.replace("\\", "/")
        for sym in symbols:
            name = sym["name"]
            refs = _merged_refs(name, file_refs)
            # Count files other than the defining file
            external_count = sum(
                1 for f in refs if f != source_norm
            )
            sym_ref_counts[(source_norm, name)] = external_count
            sym_entries.append((source_norm, sym))

    # --- Transitive liveness: filter out zero-ref symbols that are used
    #     within the same file by symbols with external refs > 0 ---
    file_sym_data: dict[str, list[tuple[str, int, int | None]]] = {}
    for source_norm, sym in sym_entries:
        file_sym_data.setdefault(source_norm, []).append(
            (sym["name"], sym["line_start"], sym.get("line_end"))
        )

    zero_ref_files = {
        sn
        for (sn, _name), count in sym_ref_counts.items()
        if count == 0
    }

    transitively_alive: set[tuple[str, str]] = set()

    for fpath in zero_ref_files:
        symbols_in_file = file_sym_data.get(fpath)
        if not symbols_in_file or len(symbols_in_file) < 2:
            continue
        cached_lines = file_lines_cache.get(fpath)
        if not cached_lines:
            continue
        alive = _compute_transitive_liveness(
            symbols_in_file,
            cached_lines,
            has_external_refs=lambda name, fp=fpath: sym_ref_counts.get((fp, name), 0) > 0,
        )
        for sym_name in alive:
            transitively_alive.add((fpath, sym_name))

    # Compute 10th percentile of non-zero reference counts
    non_zero_counts = [c for c in sym_ref_counts.values() if c > 0]
    if non_zero_counts:
        sorted_counts = sorted(non_zero_counts)
        p10_index = max(0, math.ceil(len(sorted_counts) * 0.10) - 1)
        threshold = sorted_counts[p10_index]
        threshold = min(threshold, 10)  # Cap at 10
    else:
        threshold = 0

    # Build per-file exclusion set from facts DB (exclude_from_dead_analysis)
    excluded_by_file: dict[str, set[str]] = {}
    if facts_db:
        for source_path in all_symbols:
            src_norm = source_path.replace("\\", "/")
            ff = facts_db.get_file(src_norm)
            if ff:
                excl = {e["name"] for e in ff.exports if e.get("exclude_from_dead_analysis")}
                if excl:
                    excluded_by_file[src_norm] = excl

    for source_norm, sym in sym_entries:
        name = sym["name"]
        # Internal symbols are not dead code candidates
        if sym.get("visibility") == "internal":
            continue
        # Skip symbols from files handled by AST fast path
        if exclude_files and source_norm in exclude_files:
            continue
        # Skip test file symbols
        if file_roles and file_roles.get(source_norm) == "test":
            continue
        # Skip symbols excluded from dead analysis (framework-registered, etc.)
        if source_norm in excluded_by_file and name in excluded_by_file[source_norm]:
            continue
        ext_count = sym_ref_counts[(source_norm, name)]

        if ext_count == 0:
            if (source_norm, name) in transitively_alive:
                continue  # Skip — transitively alive via within-file usage
            zero_ref.append(DeadCodeCandidate(
                source_path=source_norm,
                name=name,
                kind=sym["kind"],
                line_start=sym["line_start"],
                line_end=sym.get("line_end"),
                ref_count=0,
            ))
        elif ext_count <= threshold:
            # Build GrepHit objects
            refs = _merged_refs(name, file_refs)
            grep_hits: list[GrepHit] = []
            for ref_file, line_numbers in refs.items():
                if ref_file == source_norm:
                    continue
                cached_lines = file_lines_cache.get(ref_file)
                if not cached_lines:
                    continue
                for ln in line_numbers:
                    context = _extract_context(cached_lines, ln)
                    grep_hits.append(GrepHit(
                        file_path=ref_file,
                        line_number=ln,
                        context=context,
                    ))
            low_ref.append(DeadCodeCandidate(
                source_path=source_norm,
                name=name,
                kind=sym["kind"],
                line_start=sym["line_start"],
                line_end=sym.get("line_end"),
                ref_count=ext_count,
                grep_hits=grep_hits,
            ))

    return zero_ref, low_ref


def _all_importers_ast_extracted(symbol_path: str, facts_db: FactsDB) -> bool:
    """Check if all importers of a symbol have AST-extracted facts."""
    for importer_path in facts_db.importers_of(symbol_path):
        importer_facts = facts_db.get_file(importer_path)
        if not importer_facts or importer_facts.extraction_method != "ast":
            return False
    return True


def _group_symbols_by_file(
    all_symbols: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Group symbols by their source file path (normalized)."""
    result: dict[str, list[dict]] = {}
    for source_path, symbols in all_symbols.items():
        source_norm = source_path.replace("\\", "/")
        result.setdefault(source_norm, []).extend(symbols)
    return result


def _build_interface_alive_methods(facts_db: FactsDB) -> set[str]:
    """Build set of 'ClassName.method' names alive via interface/class contracts.

    A method is alive if any of these hold:
    1. Its class has a base class whose same-named method has
       exclude_from_dead_analysis=True (abstract/framework decorator).
    2. It is ``__init__`` and its class has cross-file references
       (constructor is called implicitly when the class is instantiated).
    3. It is ``__post_init__`` and its class is a dataclass that is alive.

    Handles multi-level inheritance via fixpoint iteration.
    """
    # Phase 1 — collect class metadata from all AST-extracted files.
    class_bases: dict[str, list[str]] = {}        # ClassName -> [BaseName, ...]
    class_file: dict[str, str] = {}               # ClassName -> source path
    class_decorators: dict[str, list[str]] = {}   # ClassName -> decorator names

    for file_path in facts_db.all_files():
        file_facts = facts_db.get_file(file_path)
        if not file_facts or file_facts.extraction_method != "ast":
            continue
        for exp in file_facts.exports:
            if exp.get("kind") != "class":
                continue
            cls_name = exp["name"]
            class_file[cls_name] = file_path
            class_decorators[cls_name] = exp.get("decorators", [])
            bases = exp.get("bases") or exp.get("implements") or []
            if bases:
                class_bases[cls_name] = bases

    # Phase 2 — resolve base class names to their defining files.
    #   base_name could be a simple name ("LLMProvider") or qualified
    #   ("module.LLMProvider").  Try same-file first, then imports.
    def _resolve_base(derived_file: str, base_name: str) -> str | None:
        """Return the source file that defines *base_name*, or None."""
        simple = base_name.rsplit(".", 1)[-1]
        # Already indexed directly?
        if simple in class_file:
            return class_file[simple]
        # Check imports of the derived file.
        derived_facts = facts_db.get_file(derived_file)
        if not derived_facts:
            return None
        for imp in derived_facts.imports:
            names = imp.get("names", [])
            name_map = imp.get("name_map", {})
            if simple in names or simple in name_map.values():
                resolved = facts_db.resolve_import_source(
                    derived_file, imp.get("source", "")
                )
                if resolved:
                    return resolved
        return None

    # Phase 3 — propagate interface methods down the class hierarchy.
    alive: set[str] = set()  # qualified "DerivedClass.method" strings

    # Fixpoint: keep propagating until no new methods are discovered.
    changed = True
    while changed:
        changed = False
        for cls_name, bases in class_bases.items():
            derived_file = class_file.get(cls_name, "")
            for base_name in bases:
                simple_base = base_name.rsplit(".", 1)[-1]
                base_file = _resolve_base(derived_file, base_name)
                if not base_file:
                    continue
                base_facts = facts_db.get_file(base_file)
                if not base_facts:
                    continue
                for exp in base_facts.exports:
                    if exp.get("kind") != "function":
                        continue
                    full_name = exp["name"]
                    if "." not in full_name:
                        continue
                    base_cls, method_name = full_name.rsplit(".", 1)
                    if base_cls != simple_base:
                        continue
                    # If base method is abstract/framework OR already marked alive
                    if exp.get("exclude_from_dead_analysis") or full_name in alive:
                        qualified = f"{cls_name}.{method_name}"
                        if qualified not in alive:
                            alive.add(qualified)
                            changed = True

    # Phase 4 — __init__ and __post_init__ on instantiated classes.
    for cls_name, file_path in class_file.items():
        cls_refs = facts_db.cross_file_references(cls_name, file_path)
        if cls_refs:
            alive.add(f"{cls_name}.__init__")
            if "dataclass" in class_decorators.get(cls_name, []):
                alive.add(f"{cls_name}.__post_init__")

    return alive


async def detect_dead_code_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> tuple[list[Finding], set[tuple[str, str]]]:
    """Detect dead code through the unified Claim Builder + Triage pipeline.

    Mechanical propose (AST fast path + grep reference scan) feeds the Claim
    Builder; Triage decides each claim under the unified rubric. AST-proven
    candidates whose built evidence shows a clean zero (no graph references,
    no textual matches over a non-empty repo sweep) are confirmed mechanically
    at confidence 1.0 with no LLM call. An AST-proven candidate whose sweep
    finds textual hits — a potential dynamic-dispatch key, a doc mention — is
    demoted to the ordinary Triage batch instead: the AST graph cannot see
    string-keyed reachability, but the text sweep can.

    Args:
        provider: LLM provider for Triage calls (injected, not owned)
        config: Osoji configuration
        on_progress: Optional callback (completed, total, path, status)

    Returns:
        Tuple of (decided Findings — all verdicts; callers keep ``confirmed`` —
        and the (path, symbol) keys that were confirmed without an LLM call).
    """
    # --- AST fast path: resolve symbols in fully-AST-extracted graphs ---
    facts_db = FactsDB(config)
    all_symbols = load_all_symbols(config)
    file_roles = load_file_roles(config)
    interface_alive = _build_interface_alive_methods(facts_db)

    ast_candidates: list[DeadCodeCandidate] = []
    ast_resolved_files: set[str] = set()

    for source_path, symbols in _group_symbols_by_file(all_symbols).items():
        file_facts = facts_db.get_file(source_path)
        if not (file_facts and file_facts.extraction_method == "ast"):
            continue
        if not _all_importers_ast_extracted(source_path, facts_db):
            continue
        ast_resolved_files.add(source_path)

        # Skip test files — add to ast_resolved_files (so grep path skips them)
        # but don't process their symbols as dead code candidates
        if file_roles.get(source_path) == "test":
            continue

        # Build exclusion sets for this file (AST-extracted facts are authoritative)
        excluded_names = {
            e["name"] for e in file_facts.exports
            if e.get("exclude_from_dead_analysis")
        }
        exported_names = {e["name"] for e in file_facts.exports}

        for sym in symbols:
            if sym.get("visibility") == "internal":
                continue
            if sym["name"] in excluded_names:
                continue
            # Only consider symbols present in AST export list
            if sym["name"] not in exported_names:
                continue
            refs = facts_db.cross_file_references(sym["name"], source_path)
            if not refs:
                # Skip symbols alive via interface contracts or constructor patterns
                if sym["name"] in interface_alive:
                    continue
                ast_candidates.append(DeadCodeCandidate(
                    source_path=source_path,
                    name=sym["name"],
                    kind=sym["kind"],
                    line_start=sym["line_start"],
                    line_end=sym.get("line_end"),
                    ref_count=0,
                ))

        # --- Transitive liveness for this file ---
        zero_ref_in_file = {c.name for c in ast_candidates if c.source_path == source_path}
        if zero_ref_in_file and len(symbols) >= 2:
            src_path = config.root_path / source_path
            try:
                file_lines = src_path.read_text(errors="ignore").splitlines()
            except OSError:
                file_lines = []
            if file_lines:
                sym_tuples = [
                    (s["name"], s["line_start"], s.get("line_end"))
                    for s in symbols
                    if s["name"] not in excluded_names
                ]
                alive = _compute_transitive_liveness(
                    sym_tuples, file_lines,
                    has_external_refs=lambda name: name not in zero_ref_in_file,
                )
                # Remove transitively-alive candidates
                ast_candidates = [c for c in ast_candidates
                                  if not (c.source_path == source_path and c.name in alive)]

    # --- Grep path: only for symbols NOT in fully-AST-resolved files ---
    zero_refs, low_refs = scan_references(
        config, exclude_files=ast_resolved_files,
        file_roles=file_roles, facts_db=facts_db,
    )
    all_candidates = zero_refs + low_refs

    # One build context per run: facts and symbols are already loaded.
    ctx = BuildContext(config, facts_db=facts_db, symbols_by_file=all_symbols)

    # AST-proven candidates: mechanical confirm on a clean sweep, demotion to
    # Triage on any textual hit.
    mechanical: list[Finding] = []
    mechanical_keys: set[tuple[str, str]] = set()
    demoted: list[Claim] = []
    ast_findings = [
        finding_from_dead_code_candidate(c, ast_proven=True) for c in ast_candidates
    ]
    for claim in build_junk_claims(ast_findings, ctx):
        finding = claim.finding
        if _clean_zero_reference(claim):
            kind = _scanner_meta(finding).get("kind", "symbol")
            mechanical.append(replace(
                finding,
                verdict="confirmed",
                confidence=1.0,
                triage_reasoning=(
                    "No cross-file references found (AST-proven; repo-wide "
                    "text sweep found zero matches)"
                ),
                suggested_fix=f"Remove {kind} `{finding.symbol}`",
            ))
            mechanical_keys.add((finding.path, finding.symbol or ""))
        else:
            demoted.append(claim)

    if mechanical or demoted:
        print(
            f"  AST-proven dead: {len(mechanical)} symbol(s) confirmed mechanically, "
            f"{len(demoted)} demoted to Triage "
            f"({len(ast_resolved_files)} file(s) skipped from grep)",
            flush=True,
        )

    print(
        f"  Found {len(zero_refs)} zero-reference symbol(s), "
        f"{len(low_refs)} low-reference candidate(s) "
        f"({len(all_candidates)} total for Triage)",
        flush=True,
    )

    grep_findings = [finding_from_dead_code_candidate(c) for c in all_candidates]
    claims = demoted + build_junk_claims(grep_findings, ctx)
    if not claims:
        return mechanical, mechanical_keys

    decided, _in_tokens, _out_tokens = await decide_junk_claims(
        claims, config, provider, on_progress=on_progress
    )
    return mechanical + decided, mechanical_keys


def _clean_zero_reference(claim: Claim) -> bool:
    """True iff the built evidence shows an honest zero — no graph or textual
    references over a non-empty, non-truncated sweep. Anything else (any hit,
    a sweep that could not run, or a corpus cut off at its cap) is Triage's
    call, not a mechanical proof."""

    for ev in claim.finding.evidence:
        if ev.kind == "cross_file_reference":
            refs = ev.payload.get("references") or []
            scope = ev.payload.get("scan_scope") or {}
            return (
                not refs
                and scope.get("files_scanned", 0) > 0
                and not scope.get("truncated")
            )
    return False


class DeadCodeAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects cross-file dead code (unused symbols)."""

    @property
    def name(self) -> str:
        return "dead_code"

    @property
    def description(self) -> str:
        return "Detect cross-file dead code (unused symbols)"

    @property
    def cli_flag(self) -> str:
        return "dead-code"

    async def analyze_async(self, provider, config, on_progress=None):
        decided, mechanical_keys = await detect_dead_code_async(
            provider, config, on_progress
        )
        findings = []
        for f in decided:
            if f.verdict != "confirmed":
                continue
            kind = _scanner_meta(f).get("kind", "symbol")
            name = f.symbol or ""
            findings.append(JunkFinding(
                source_path=f.path,
                name=name,
                kind=kind,
                category="dead_symbol",
                line_start=f.line_start or 1,
                line_end=f.line_end,
                confidence=f.confidence if f.confidence is not None else 0.0,
                reason=f.triage_reasoning or "",
                remediation=f.suggested_fix or f"Remove {kind} `{name}`",
                original_purpose=f"{kind} `{name}`",
                confidence_source=(
                    "ast_proven" if (f.path, name) in mechanical_keys else "llm_inferred"
                ),
                finding_id=f.id,
                verdict=f.verdict,
            ))
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(decided) + len(mechanical_keys),
            analyzer_name=self.name,
        )
