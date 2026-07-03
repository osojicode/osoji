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
from pathlib import Path
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
_MAX_NEEDLES = 5
_CONTEXT_LINES = 2
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
        """Root-relative POSIX paths of the text-scan corpus (cached)."""

        if self._scan_files is None:
            files: list[str] = []
            root = self.config.root_path
            try:
                for path in root.glob("**/*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(root)
                    if any(part in _SKIP_DIRS for part in rel.parts):
                        continue
                    files.append(rel.as_posix())
                    if len(files) >= _MAX_SCAN_FILES:
                        break
            except OSError:
                pass
            self._scan_files = files
        return self._scan_files


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
    # 1. Backtick-quoted simple names
    for m in re.finditer(r"`(\w+)`", description):
        name = m.group(1)
        if name.lower() not in _SYMBOL_FILLER and name not in seen:
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


def _backticked_names(text: str) -> list[str]:
    seen: list[str] = []
    for match in re.finditer(r"`(\w+)`", text):
        name = match.group(1)
        if name.lower() not in _SYMBOL_FILLER and name not in seen:
            seen.append(name)
    return seen


def _scan_needles(finding: Finding) -> tuple[list[str], list[str]]:
    """(symbol_needles, literal_needles) for the text scan.

    A flagged symbol wins outright. Symbol-less findings use what the claim
    prose explicitly marks — backticked identifiers and quoted literals —
    falling back to the loose prose extractor only when neither exists
    (ablation r1 lesson: prose words like 'Implicit' make junk needles while
    the actual contract literal sits in quotes).
    """

    text = _claim_text(finding)
    literals = _quoted_literals(text)
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
    """1-based inclusive numbered snippet, clamped to the file."""

    lo = max(1, start)
    hi = min(len(lines), end)
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(lo, hi + 1))


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
        facts = ctx.facts()
        facts_symbols = (
            [finding.symbol]
            if finding.symbol
            else _extract_all_symbols_from_debris(_claim_text(finding))
        )
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
        # usage lives in the same file; ablation r1 lesson).
        needles = [(sym, rf"\b{re.escape(sym)}\b") for sym in symbols]
        needles += [(lit, re.escape(lit)) for lit in literals]
        flagged_lo = finding.line_start or 0
        flagged_hi = finding.line_end or flagged_lo
        scan_files = ctx.scan_files()
        for needle, pattern in needles:
            regex = re.compile(pattern)
            hits = 0
            for rel in scan_files:
                same_file = rel == source
                lines = ctx.read_lines(rel)
                if lines is None:
                    continue
                for lineno, line in enumerate(lines, start=1):
                    if same_file and flagged_lo <= lineno <= flagged_hi:
                        continue  # the declaration itself is not a reference
                    if not regex.search(line):
                        continue
                    context = "\n".join(
                        lines[max(0, lineno - 1 - _CONTEXT_LINES): lineno + _CONTEXT_LINES]
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
                    references.append(entry)
                    hits += 1
                    if hits >= _MAX_HITS_PER_NEEDLE:
                        break
                if hits >= _MAX_HITS_PER_NEEDLE:
                    break

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
            "files_scanned": len(scan_files),
            "needles": [n for n, _ in needles],
            "same_file_swept": True,
        }
        if not references and not export_surface and not scan_files:
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
                    "text": "\n".join(lines[preceding_start - 1: anchor - 1]),
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
                    "text": "\n".join(lines[head_start - 1: head_end]),
                }
            )
        if not blocks:
            return []
        return [Evidence(kind=self.kind, payload={"file": rel, "blocks": blocks})]


class ShadowDocBuilder(EvidenceBuilder):
    """Shadow docs as compressed-code evidence: file scope always; directory
    scope for description gaps (the potentially-architectural case)."""

    kind = "shadow_doc_claim"

    def build(self, finding: Finding, ctx: BuildContext) -> list[Evidence]:
        rel = finding.path.replace("\\", "/")
        evidence: list[Evidence] = []
        file_shadow = load_shadow_content(ctx.config, rel)
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
            try:
                dir_shadow = dir_shadow_path.read_text(encoding="utf-8")
            except OSError:
                dir_shadow = ""
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
