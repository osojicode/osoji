"""Concrete evidence builders for the mechanized Claim Builder (V1-4).

Each builder mechanizes an evidence kind the Triage LLM consistently consulted
in the Phase B exploration traces (osojicode/work#27; the mined requirements
doc is committed at ``tests/fixtures/bootstrap/mining/mining-report.md``):

- ``cross_file_reference`` — the repo-wide reference sweep (FactsDB graph +
  mechanical text scan) plus per-site context, honest scan scope, and
  export-surface facts. Zero hits over a non-empty scope is evidence-of-absence
  (the canonical case-FOR a reachability claim), not missing evidence.
- ``surrounding_code`` — the flagged region, symbol-anchored against line drift.
- ``declared_intent`` — positional text blocks where stated intent lives
  (lines preceding the region; the head of the enclosing symbol).
- ``shadow_doc_claim`` — the compressed-code substrate at file scope
  (+ directory scope for description gaps).
- ``type_signature`` — the legacy latent-bug type-definition lookup.

Positional-vs-semantic discipline (see osojicode/wiki
``concepts/self-sufficient-claims.md``): builders report *where* things are and
*what surrounds* them; the LLM supplies interpretation. The declared-intent
builder is the sharpest example — it does not know what a comment is in any
language; it hands the LLM the positional blocks where declarations of intent
conventionally live and lets the model's language knowledge fire.

Builders never raise; a builder that cannot gather returns ``[]``. Sufficiency
(``insufficient_evidence``) is decided by the schema layer in
:mod:`osoji.claim_builder`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Config
from .evidence import BUILDERS, Evidence, EvidenceBuilder
from .findings import Finding
from .junk import load_shadow_content

# The text scan sweeps the same corpus the exploration greps ran over
# (triage_exec._iter_files semantics) so the mechanization matches the mined
# behavior; the corpus deliberately extends beyond the flagged file pair — the
# one true exploration miss in Phase B was deciding evidence in a third file.
from .triage_exec import _SKIP_DIRS

_MAX_SCAN_FILES = 5000
_MAX_HITS_PER_NEEDLE = 20
_MAX_HITS_PER_FILE = 3  # diversity: one noisy file must not fill the budget
_MAX_SCAN_ENTRIES_PER_CLAIM = 40  # bounds the rendered claim payload
_MAX_NEEDLES = 5
_CONTEXT_LINES = 2
_MAX_CONTEXT_LINE_CHARS = 200  # mirrors ExplorationExecutor's grep truncation
_REGION_PAD = 10
_ENCLOSING_HEAD_LINES = 15
_SHADOW_EXCERPT_CHARS = 2000


@dataclass
class BuildContext:
    """Shared, lazily-populated context for one Claim-Builder run.

    Builders are stateless singletons; everything environmental (root, facts,
    symbols, file cache) is injected through this object so the audit path and
    the bootstrap harness can run the same builders against different roots.
    """

    config: Config
    facts_db: Any | None = None
    symbols_by_file: dict[str, list[dict]] | None = None
    _file_cache: dict[str, list[str] | None] = field(default_factory=dict, repr=False)
    _scan_files: list[str] | None = field(default=None, repr=False)
    _scan_truncated: bool = field(default=False, repr=False)

    def facts(self) -> Any:
        if self.facts_db is None:
            from .facts import FactsDB

            self.facts_db = FactsDB(self.config)
        return self.facts_db

    def symbols(self) -> dict[str, list[dict]]:
        if self.symbols_by_file is None:
            from .symbols import load_all_symbols

            self.symbols_by_file = load_all_symbols(self.config)
        return self.symbols_by_file

    def read_lines(self, rel_path: str) -> list[str] | None:
        """Cached line read of a root-relative file; None if unreadable."""

        key = rel_path.replace("\\", "/")
        if key not in self._file_cache:
            full = self.config.root_path / key
            try:
                self._file_cache[key] = full.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                self._file_cache[key] = None
        return self._file_cache[key]

    def scan_files(self) -> list[str]:
        """Root-relative POSIX paths of the text-scan corpus (cached).

        The corpus is the walker's repo view (git-tracked / ignore-filtered),
        NOT a raw directory glob. A raw glob dilutes the sweep with
        git-ignored build outputs and vendored trees, and once the cap bites,
        truncation is corpus pollution with the sign flipped: on
        mcp-debugger (12k glob entries vs 822 repo files) the flagged file
        itself fell outside the capped corpus and a "zero matches" sweep
        mechanically confirmed a symbol that its own file uses four times.
        The skip-dir filter is kept for the walker's non-git rglob fallback.
        """

        if self._scan_files is None:
            from .walker import list_repo_files

            files: list[str] = []
            root = self.config.root_path
            try:
                paths, _used_git = list_repo_files(self.config)
                for path in paths:
                    full = path if path.is_absolute() else root / path
                    if not full.is_file():
                        continue
                    rel = full.relative_to(root)
                    if any(part in _SKIP_DIRS for part in rel.parts):
                        continue
                    if len(files) >= _MAX_SCAN_FILES:
                        # Cap reached with corpus remaining: record the
                        # truncation so downstream consumers can refuse to
                        # treat a zero-hit sweep as evidence-of-absence.
                        self._scan_truncated = True
                        break
                    files.append(rel.as_posix())
            except OSError:
                pass
            self._scan_files = files
        return self._scan_files

    def scan_truncated(self) -> bool:
        """True iff the last :meth:`scan_files` corpus hit the size cap."""

        self.scan_files()
        return self._scan_truncated


# --- shared positional helpers (relocated verbatim from claim_builder V1-3) --

_SYMBOL_FILLER = {
    "field", "defined", "never", "set", "used", "unused", "dead", "code",
    "the", "and", "but", "not", "this", "that", "from", "with", "are",
    "was", "were", "has", "have", "been", "being",
}


def _extract_all_symbols_from_debris(description: str) -> list[str]:
    """Extract all plausible symbol names from a debris finding description."""
    names: list[str] = []
    seen: set[str] = set()
    # 1. Backtick-quoted names (dotted allowed — FactsDB resolves
    #    `Class.method` including bare-method dispatch matching)
    for m in re.finditer(r"`([\w.]+)`", description):
        name = m.group(1).strip(".")
        if name and name.lower() not in _SYMBOL_FILLER and name not in seen:
            names.append(name)
            seen.add(name)
    # 2. PascalCase compounds (catches type names in plain text). Linear
    #    tokenize + predicate instead of the prior nested quantifier
    #    `[A-Z][a-z]\w*(?:[A-Z][a-z]\w*)+`, which backtracks catastrophically on
    #    inputs like "AaAaAa…" (ReDoS — and ``description`` is LLM-generated).
    #    Extracts the IDENTICAL set: a maximal word run that *starts* with
    #    `[A-Z][a-z]` and contains >=2 such segments (the old anchored pattern
    #    could only ever match a whole word, from a starting `[A-Z][a-z]`, with
    #    a repeated `[A-Z][a-z]` segment — i.e. >=2 segments total).
    for m in re.finditer(r"\w+", description):
        word = m.group()
        if re.match(r"[A-Z][a-z]", word) and len(re.findall(r"[A-Z][a-z]", word)) >= 2:
            if word not in seen:
                names.append(word)
                seen.add(word)
    # 3. Fallback: bare identifier words (existing logic)
    if not names:
        for word in description.split():
            word = word.strip(".,;:()")
            if re.match(r"^[a-zA-Z_]\w{2,}$", word) and word.lower() not in _SYMBOL_FILLER:
                if word not in seen:
                    names.append(word)
                    seen.add(word)
                    break  # just one fallback
    return names


def _lookup_type_definitions(
    config: Config,
    type_names: list[str],
    symbols_by_file: dict[str, list[dict]],
) -> list[dict]:
    """Look up class/type definitions in the symbols DB and return source snippets.

    Returns list of {"type_name": str, "file": str, "source": str}.
    """
    results: list[dict] = []
    seen: set[str] = set()
    type_set = set(type_names)
    for file_path, symbols in symbols_by_file.items():
        for sym in symbols:
            name = sym.get("name", "")
            if name in type_set and name not in seen and sym.get("kind") in ("class", "type"):
                full_path = config.root_path / file_path
                if not full_path.exists():
                    continue
                try:
                    lines = full_path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                start = sym.get("line_start", 1) - 1
                end = min(sym.get("line_end", start + 30), start + 50)
                snippet = "\n".join(
                    f"{start + 1 + i}: {l}" for i, l in enumerate(lines[start:end])
                )
                results.append({"type_name": name, "file": file_path, "source": snippet})
                seen.add(name)
    return results


def _infer_variable_type(
    config: Config,
    source_path: str,
    line_number: int | None,
    description: str,
) -> list[str]:
    """Extract type names from variable annotations near the finding line.

    Looks for patterns like `var: TypeName` in function signatures and assignments
    near the finding. Returns PascalCase type names found.
    """
    if not line_number:
        return []
    full_path = config.root_path / source_path
    if not full_path.exists():
        return []
    # Extract variable names from dotted backtick references (e.g. `options.field`)
    var_names: set[str] = set()
    for m in re.finditer(r"`(\w+)\.\w+`", description):
        var_names.add(m.group(1))
    if not var_names:
        return []

    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    start = max(0, line_number - 40)
    type_names: list[str] = []
    for var in var_names:
        for i in range(line_number - 1, start - 1, -1):
            line = lines[i] if i < len(lines) else ""
            match = re.search(rf"\b{re.escape(var)}\s*:\s*[\"']?([A-Z]\w+)", line)
            if match:
                type_names.append(match.group(1))
                break
    return type_names


def _claim_text(finding: Finding) -> str:
    return f"{finding.contract_claim} {finding.observed_behavior}"


def _scanner_meta(finding: Finding) -> dict[str, Any]:
    """Payload of the finding's propose-time ``scanner_metadata`` Evidence, if any.

    V1-5 native detectors attach one such Evidence carrying scanner-chosen
    ``scan_needles`` and ``priority_paths`` (the detector knows its grep names
    and where its hits were; the builder should not re-guess them from prose).
    """

    for ev in finding.evidence:
        if ev.kind == "scanner_metadata":
            return ev.payload
    return {}


def _match_in_quotes(line: str, pos: int) -> bool:
    """Positional check: is column ``pos`` inside a quoted span on this line?

    A single-line state machine over quote characters (``'``, ``"``, backtick)
    with naive backslash-escape skipping — deliberately no language semantics
    (which quote styles exist, multi-line strings, comment syntax). The flag is
    rendered as a positional marker; the LLM judges what the quoting means.
    """

    quote: str | None = None
    i = 0
    while i < pos and i < len(line):
        ch = line[i]
        if quote is None:
            if ch in "'\"`":
                quote = ch
        elif ch == "\\":
            i += 1
        elif ch == quote:
            quote = None
        i += 1
    return quote is not None


def _backticked_names(text: str) -> list[str]:
    """Backticked identifiers, including dotted ones.

    A dotted name contributes both the qualified form and its bare last
    segment — `Class.method` reachability lives at `obj.method(` call sites
    and string-dispatch keys that name only the method (the dead_symbol-001
    lesson: the plain-word pattern silently skipped dotted names, so the
    method was never swept and its dispatch string stayed invisible).
    """

    seen: list[str] = []
    for match in re.finditer(r"`([\w.]+)`", text):
        name = match.group(1).strip(".")
        candidates = [name]
        if "." in name:
            candidates.append(name.rsplit(".", 1)[-1])
        for candidate in candidates:
            if candidate and candidate.lower() not in _SYMBOL_FILLER and candidate not in seen:
                seen.append(candidate)
    return seen


def _scan_needles(finding: Finding) -> tuple[list[str], list[str]]:
    """(symbol_needles, literal_needles) for the text scan.

    A detector-supplied ``scan_needles`` list (scanner_metadata) wins outright —
    the detector knows its grep names better than prose extraction does (e.g.
    dead-parameter claims sweep the *function*, never the noisy bare parameter
    name). Otherwise a flagged symbol wins. Symbol-less findings use what the
    claim prose explicitly marks — backticked identifiers and quoted literals —
    falling back to the loose prose extractor only when neither exists
    (ablation r1 lesson: prose words like 'Implicit' make junk needles while
    the actual contract literal sits in quotes).
    """

    text = _claim_text(finding)
    literals = _quoted_literals(text)
    supplied = [str(n) for n in _scanner_meta(finding).get("scan_needles", ()) if n]
    if supplied:
        return supplied[:_MAX_NEEDLES], literals if finding.gap_type == "contract" else []
    if finding.symbol:
        return [finding.symbol], literals if finding.gap_type == "contract" else []
    symbols = _backticked_names(text)[:_MAX_NEEDLES]
    if not symbols and not literals:
        symbols = _extract_all_symbols_from_debris(text)[:_MAX_NEEDLES]
    return symbols, literals


def _quoted_literals(text: str) -> list[str]:
    """String literals quoted in the claim prose ('x' or "x"); not backticks —
    backticked names are symbol needles."""

    seen: list[str] = []
    for match in re.finditer(r"['\"]([^'\"\n]{2,80})['\"]", text):
        value = match.group(1)
        if value not in seen:
            seen.append(value)
    return seen[:_MAX_NEEDLES]


def _named_paths(finding: Finding, ctx: BuildContext) -> list[str]:
    """Root-relative paths the claim prose names and that exist in the corpus.

    Contract findings name their file tuple in prose ("produced in
    src/osoji/shadow.py, checked in tests/test_x.py") — those files carry the
    deciding evidence and must be swept before the hit cap can fill with
    incidental matches (the file-tuple minimum context, mechanized)."""

    paths: list[str] = []
    for token in re.findall(r"[\w./\\-]+", _claim_text(finding)):
        if "/" not in token and "\\" not in token:
            continue
        norm = token.strip(".,;:'\"`").replace("\\", "/")
        if norm and norm not in paths and ctx.read_lines(norm) is not None:
            paths.append(norm)
    return paths


def _find_symbol_entry(
    symbols_by_file: dict[str, list[dict]], rel_path: str, name: str
) -> dict | None:
    for sym in symbols_by_file.get(rel_path, []):
        if sym.get("name") == name and sym.get("line_start"):
            return sym
    return None


def _enclosing_symbol(
    symbols_by_file: dict[str, list[dict]], rel_path: str, line: int
) -> dict | None:
    """Smallest symbols-DB span containing ``line`` (language-agnostic)."""

    best: dict | None = None
    for sym in symbols_by_file.get(rel_path, []):
        start, end = sym.get("line_start"), sym.get("line_end")
        if not start or not end or not (start <= line <= end):
            continue
        if best is None or (end - start) < (best["line_end"] - best["line_start"]):
            best = {"name": sym.get("name"), "kind": sym.get("kind"),
                    "line_start": start, "line_end": end}
    return best


def _numbered(lines: list[str], start: int, end: int) -> str:
    """1-based inclusive numbered snippet, clamped to the file; long lines
    truncated so a minified one-liner cannot balloon the claim payload."""

    lo = max(1, start)
    hi = min(len(lines), end)
    return "\n".join(
        f"{i}: {lines[i - 1][:_MAX_CONTEXT_LINE_CHARS * 2]}" for i in range(lo, hi + 1)
    )


# --- builders ----------------------------------------------------------------


class CrossFileReferenceBuilder(EvidenceBuilder):
    """Repo-wide reference sweep: FactsDB graph + mechanical text scan.

    Payload:
        references: facts refs (``source: "facts"``) then text-scan hits
            (``source: "text_scan"``, with line + surrounding context lines).
        shadow_excerpts: shadow docs of the top referencing files (legacy shape).
        scan_scope: {files_scanned, needles} — makes zero-hit results honest
            evidence-of-absence rather than silence.
        export_surface: whether the flagged symbol is part of the flagged
            file's export surface (the "external consumers" handle for Triage).
    """

    kind = "cross_file_reference"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        source = finding.path.replace("\\", "/")
        symbols, literals = _scan_needles(finding)
        if not symbols and not literals:
            return []

        references: list[dict] = []

        # FactsDB graph refs — legacy best-per-symbol selection preserved
        # (loose extractor on purpose: facts lookups are cheap and precise).
        # Detector-supplied needles are tried too: a dead-parameter claim's
        # deciding graph refs hang off the function name, not `func.param`.
        facts = ctx.facts()
        supplied = [str(n) for n in _scanner_meta(finding).get("scan_needles", ()) if n]
        if supplied:
            facts_symbols = supplied
        elif finding.symbol:
            facts_symbols = [finding.symbol]
        else:
            facts_symbols = _extract_all_symbols_from_debris(_claim_text(finding))
        best_refs: list[dict] = []
        for sym in facts_symbols:
            try:
                refs = facts.cross_file_references(sym, source)
            except Exception:
                refs = []
            if len(refs) > len(best_refs):
                best_refs = refs
        references.extend({**ref, "source": "facts"} for ref in best_refs)

        # Mechanical text scan — the whole corpus, beyond any file pair, and
        # the flagged file itself outside the flagged region (wrapper-pattern
        # usage lives in the same file; ablation r1 lesson). Identifier-like
        # literals get word-boundary guards ('ast' must not match 'fastest';
        # ablation r2 lesson).
        needles = [(sym, rf"\b{re.escape(sym)}\b") for sym in symbols]
        needles += [
            (lit, rf"\b{re.escape(lit)}\b" if re.fullmatch(r"\w+", lit) else re.escape(lit))
            for lit in literals
        ]
        flagged_lo = finding.line_start or 0
        flagged_hi = finding.line_end or flagged_lo

        # Sweep order decides what survives the hit cap: detector-supplied
        # priority paths (grep-hit files, importers) and claim-named files
        # first, then by proximity to the flagged file within source-extension
        # rank, then everything else. Two mined lessons: alphabetical order
        # filled the cap with LICENSE/docs junk (r2), and raw glob order let a
        # committed fixture corpus's own trace JSONs crowd out the flagged
        # file's sibling-package usage sites (V1-5a dead_symbol-002) — the
        # nearest files in the tree are the most probative reference sites.
        named: list[str] = []
        for p in _scanner_meta(finding).get("priority_paths", ()):
            norm = str(p).replace("\\", "/")
            if norm and norm not in named and ctx.read_lines(norm) is not None:
                named.append(norm)
        for p in _named_paths(finding, ctx):
            if p not in named:
                named.append(p)
        # The flagged file is minimum context — sweep it regardless of
        # whether the (possibly capped) corpus reached it.
        if source not in named and ctx.read_lines(source) is not None:
            named.append(source)
        extensions = getattr(ctx.config, "extensions", ())
        source_parts = PurePosixPath(source).parts

        def _proximity(rel: str) -> int:
            parts = PurePosixPath(rel).parts
            shared = 0
            for a, b in zip(source_parts[:-1], parts[:-1]):
                if a != b:
                    break
                shared += 1
            return shared

        rest = [f for f in ctx.scan_files() if f not in named]
        ordered = named + sorted(
            rest,
            key=lambda f: (0 if Path(f).suffix in extensions else 1, -_proximity(f)),
        )
        needle_totals: dict[str, int] = {}
        scan_entries = 0
        for needle, pattern in needles:
            regex = re.compile(pattern)
            hits = 0
            total = 0
            for rel in ordered:
                same_file = rel == source
                named_file = rel in named
                lines = ctx.read_lines(rel)
                if lines is None:
                    continue
                file_hits = 0
                for lineno, line in enumerate(lines, start=1):
                    if same_file and flagged_lo <= lineno <= flagged_hi:
                        continue  # the declaration itself is not a reference
                    match = regex.search(line)
                    if not match:
                        continue
                    total += 1
                    if hits >= _MAX_HITS_PER_NEEDLE or scan_entries >= _MAX_SCAN_ENTRIES_PER_CLAIM:
                        continue  # keep counting for honest totals
                    if file_hits >= _MAX_HITS_PER_FILE and not named_file:
                        continue  # diversity: cap per file, honest total still counts
                    context = "\n".join(
                        raw[:_MAX_CONTEXT_LINE_CHARS]
                        for raw in lines[
                            max(0, lineno - 1 - _CONTEXT_LINES): lineno + _CONTEXT_LINES
                        ]
                    )
                    entry = {
                        "file": rel,
                        "kind": "text_match",
                        "line": lineno,
                        "context": context,
                        "needle": needle,
                        "source": "text_scan",
                    }
                    if same_file:
                        entry["same_file"] = True
                    if _match_in_quotes(line, match.start()):
                        # Positional dynamic-dispatch signal: an exact-name hit
                        # inside a quoted span may be a reflection/registry key
                        # (the dead_symbol-001 ablation residual).
                        entry["in_string_literal"] = True
                    references.append(entry)
                    hits += 1
                    file_hits += 1
                    scan_entries += 1
            needle_totals[needle] = total

        # Export surface: is the flagged symbol part of the file's public
        # export list? Positional fact that lets Triage weigh the
        # "external consumers outside this repo" dismissal.
        export_surface: dict[str, Any] | None = None
        primary = symbols[0] if symbols else None
        if primary:
            try:
                known_files = set(facts.all_files())
                if source in known_files:
                    export_surface = {
                        "symbol": primary,
                        "exported_from_flagged_file": primary in facts.exported_names(source),
                    }
            except Exception:
                export_surface = None

        scan_scope = {
            "files_scanned": len(ordered),
            "needles": [n for n, _ in needles],
            "needle_totals": needle_totals,
            "same_file_swept": True,
        }
        if ctx.scan_truncated():
            # A capped corpus cannot support evidence-of-absence claims.
            scan_scope["truncated"] = True
        if not references and not export_surface and not ordered:
            # We could not even look — no graph, no corpus. This (and only
            # this) is the insufficient-evidence case for references.
            return []

        payload: dict[str, Any] = {
            "references": references,
            "shadow_excerpts": self._shadow_excerpts(ctx, references),
            "scan_scope": scan_scope,
        }
        if export_surface:
            payload["export_surface"] = export_surface
        return [Evidence(kind=self.kind, payload=payload)]

    @staticmethod
    def _shadow_excerpts(ctx: BuildContext, references: list[dict]) -> dict[str, str]:
        excerpts: dict[str, str] = {}
        for ref in references[:3]:
            shadow = load_shadow_content(ctx.config, ref["file"])
            if shadow:
                excerpts[ref["file"]] = shadow[:_SHADOW_EXCERPT_CHARS]
        return excerpts


class SurroundingCodeBuilder(EvidenceBuilder):
    """The flagged region ±10 lines, numbered, symbol-anchored when possible.

    Audit findings carry line numbers from the commit they were proposed at;
    anchoring on the symbols DB (or a word-boundary search nearest the claimed
    line) survives drift from cosmetic edits.
    """

    kind = "surrounding_code"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        rel = finding.path.replace("\\", "/")
        lines = ctx.read_lines(rel)
        if not lines:
            return []

        anchor = "lines"
        start = finding.line_start or 1
        end = finding.line_end or start
        if finding.symbol:
            entry = _find_symbol_entry(ctx.symbols(), rel, finding.symbol)
            if entry:
                start, end = entry["line_start"], entry.get("line_end") or entry["line_start"]
                anchor = "symbol"
            else:
                nearest = self._nearest_word_line(lines, finding.symbol, start)
                if nearest is not None:
                    start = end = nearest
                    anchor = "symbol"

        region_start = max(1, start - _REGION_PAD)
        region_end = min(len(lines), end + _REGION_PAD)
        payload: dict[str, Any] = {
            "file": rel,
            "line_start": region_start,
            "line_end": region_end,
            "snippet": _numbered(lines, region_start, region_end),
            "anchor": anchor,
        }
        enclosing = _enclosing_symbol(ctx.symbols(), rel, start)
        if enclosing and not (enclosing["line_start"] == start and enclosing["line_end"] == end):
            payload["enclosing_symbol"] = enclosing
        return [Evidence(kind=self.kind, payload=payload)]

    @staticmethod
    def _nearest_word_line(lines: list[str], symbol: str, near: int) -> int | None:
        regex = re.compile(rf"\b{re.escape(symbol)}\b")
        matches = [i for i, line in enumerate(lines, start=1) if regex.search(line)]
        if not matches:
            return None
        return min(matches, key=lambda i: abs(i - near))


class DeclaredIntentBuilder(EvidenceBuilder):
    """Positional blocks where stated intent conventionally lives.

    Two blocks: the lines immediately preceding the flagged region (comments
    live above), and the head of the enclosing symbol (doc blocks live at the
    head). The builder does not know any language's comment syntax — the LLM
    recognizes it; the builder only positions the text.
    """

    kind = "declared_intent"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        rel = finding.path.replace("\\", "/")
        lines = ctx.read_lines(rel)
        if not lines:
            return []
        anchor = finding.line_start or 1

        blocks: list[dict[str, Any]] = []
        preceding_start = max(1, anchor - _REGION_PAD)
        if preceding_start < anchor:
            blocks.append(
                {
                    "label": "preceding_lines",
                    "line_start": preceding_start,
                    "text": "\n".join(
                        raw[:_MAX_CONTEXT_LINE_CHARS * 2]
                        for raw in lines[preceding_start - 1: anchor - 1]
                    ),
                }
            )
        enclosing = _enclosing_symbol(ctx.symbols(), rel, anchor)
        if enclosing:
            head_start = enclosing["line_start"]
            head_end = min(enclosing["line_end"], head_start + _ENCLOSING_HEAD_LINES - 1)
            blocks.append(
                {
                    "label": "enclosing_head",
                    "line_start": head_start,
                    "symbol": enclosing["name"],
                    "text": "\n".join(
                        raw[:_MAX_CONTEXT_LINE_CHARS * 2]
                        for raw in lines[head_start - 1: head_end]
                    ),
                }
            )
        if not blocks:
            return []
        return [Evidence(kind=self.kind, payload={"file": rel, "blocks": blocks})]


def _read_text(path: Path) -> str:
    """Best-effort text read; empty string if unreadable."""

    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _scope_for(sources: list[str]) -> tuple[str, str | None]:
    """Smallest shadow scope that brackets a set of referenced source paths.

    Purely positional (path tokens only, no semantics): one distinct source →
    file scope; several sharing one parent directory → that directory's scope;
    sources spanning >=2 directories, or none at all (an unanchored/project-level
    claim) → root scope.
    """

    distinct = list(dict.fromkeys(sources))
    if not distinct:
        return ("root", None)
    if len(distinct) == 1:
        return ("file", distinct[0])
    parents = {PurePosixPath(s).parent.as_posix() for s in distinct}
    if len(parents) == 1:
        return ("directory", next(iter(parents)))
    return ("root", None)


class ShadowDocBuilder(EvidenceBuilder):
    """Shadow docs as compressed-code evidence.

    Source-anchored findings (a comment/docstring in a file that has its own
    shadow): file scope always, plus directory scope for description gaps (the
    potentially-architectural case).

    Doc-anchored description findings (V1-5d): ``finding.path`` is a prose doc
    with no file shadow, so the useful evidence is the shadow of the *source(s)
    the doc makes claims about*, attached at the smallest scope that brackets the
    claim (:func:`_scope_for`).
    """

    kind = "shadow_doc_claim"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        rel = finding.path.replace("\\", "/")
        file_shadow = load_shadow_content(ctx.config, rel)

        # V1-5d: the finding's own path has no file shadow (it is a prose doc) —
        # anchor on the source(s) the doc references instead.
        if not file_shadow and finding.gap_type == "description":
            doc_evidence = self._doc_anchored(finding, ctx)
            if doc_evidence:
                return doc_evidence

        # --- existing source-anchored behavior (owned by V1-5e; unchanged) ---
        evidence: list[Evidence] = []
        if file_shadow:
            evidence.append(
                Evidence(
                    kind=self.kind,
                    payload={
                        "file": rel,
                        "scope": "file",
                        "excerpt": file_shadow[:_SHADOW_EXCERPT_CHARS],
                    },
                )
            )
        if finding.gap_type == "description":
            dir_shadow_path = ctx.config.shadow_path_for_dir(
                (ctx.config.root_path / rel).parent
            )
            dir_shadow = _read_text(dir_shadow_path)
            if dir_shadow:
                evidence.append(
                    Evidence(
                        kind=self.kind,
                        payload={
                            "file": rel,
                            "scope": "directory",
                            "excerpt": dir_shadow[:_SHADOW_EXCERPT_CHARS],
                        },
                    )
                )
        return evidence

    def _doc_anchored(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        """Smallest-sufficient shadow scope for a description-gap DOC finding."""

        sources = self._referenced_sources(finding, ctx)
        scope, anchor = _scope_for(sources)
        if scope == "file":
            body = load_shadow_content(ctx.config, anchor or "")
            label = anchor or ""
        elif scope == "directory":
            body = _read_text(
                ctx.config.shadow_path_for_dir(ctx.config.root_path / (anchor or ""))
            )
            label = anchor or ""
        else:  # root
            body = _read_text(ctx.config.shadow_path_for_dir(ctx.config.root_path))
            label = ""
        if not body:
            return []
        return [
            Evidence(
                kind=self.kind,
                payload={
                    "file": label,
                    "scope": scope,
                    "excerpt": body[:_SHADOW_EXCERPT_CHARS],
                },
            )
        ]

    @staticmethod
    def _referenced_sources(finding: Finding, ctx: BuildContext) -> list[str]:
        """Source paths a doc finding names: the cited ``shadow_ref`` plus any
        path-like ``search_terms`` that resolve to an existing shadow doc.

        Positional only — a term counts iff it names a path (``/`` present) that
        the shadow tree actually knows, so the scope is derived from the finding's
        own data rather than guessed."""

        meta = _scanner_meta(finding)
        sources: list[str] = []
        shadow_ref = meta.get("shadow_ref")
        if shadow_ref:
            norm = str(shadow_ref).replace("\\", "/")
            if norm and norm not in sources:
                sources.append(norm)
        for term in meta.get("search_terms", ()):
            norm = str(term).replace("\\", "/")
            if "/" in norm and norm not in sources and load_shadow_content(ctx.config, norm):
                sources.append(norm)
        return sources


class TypeSignatureBuilder(EvidenceBuilder):
    """Legacy latent-bug type lookup: PascalCase names in the claim text plus
    annotation-inferred variable types, resolved through the symbols DB."""

    kind = "type_signature"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        text = _claim_text(finding)
        candidates = _extract_all_symbols_from_debris(text)
        type_names = [s for s in candidates if s and s[0].isupper() and not s.isupper()]
        type_names.extend(
            _infer_variable_type(ctx.config, finding.path, finding.line_start, text)
        )
        if not type_names:
            return []
        type_defs = _lookup_type_definitions(ctx.config, type_names, ctx.symbols())
        return [Evidence(kind=self.kind, payload=td) for td in type_defs]


BUILDERS.update(
    {
        builder.kind: builder
        for builder in (
            CrossFileReferenceBuilder(),
            SurroundingCodeBuilder(),
            DeclaredIntentBuilder(),
            ShadowDocBuilder(),
            TypeSignatureBuilder(),
        )
    }
)
