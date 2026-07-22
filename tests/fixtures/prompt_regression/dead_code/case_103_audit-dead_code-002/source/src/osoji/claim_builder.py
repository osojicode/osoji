"""Inline debris Claim Builder for V1-3.

This is the V1-3 stand-in for the mechanized Claim Builder that lands in V1-4
(``evidence.py`` ``BUILDERS``). It assembles the *same* cross-file evidence the
legacy ``audit._verify_debris_findings_async`` gathered — cross-file references
and (for latent bugs) type definitions — and attaches it as typed
:class:`~osoji.evidence.Evidence` on each :class:`~osoji.findings.Finding`, so the
unified Triage stage can decide them in claim mode.

Behavior is preserved exactly: the set of findings turned into Claims is the same
set the old verify step sent to the LLM (eligible category **and** gatherable
evidence). Eligible findings the builder cannot fill are **counted**
(``would_escalate``) for the V1-4 escalation-rate baseline but pass through
unverified — they are never escalated here (decision 1).

The three positional helpers (``_extract_all_symbols_from_debris``,
``_lookup_type_definitions``, ``_infer_variable_type``) are relocated verbatim
from ``audit.py``; they are debris-specific and move with the path they served.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Config
from .evidence import Evidence
from .findings_adapter import finding_from_debris
from .junk import load_shadow_content
from .triage import Claim


def _is_eligible(finding: dict) -> bool:
    """Same eligibility gate as the legacy debris verify step."""

    category = finding.get("category", "")
    if category in ("dead_code", "latent_bug"):
        return True
    if category == "stale_comment" and finding.get("cross_file_verification_needed"):
        return True
    return False


def build_debris_claims(
    config: Config,
    raw_debris: list[dict],
    *,
    facts_db: Any | None = None,
    symbols_by_file: dict[str, list[dict]] | None = None,
) -> tuple[list[Claim], list[int], int]:
    """Assemble debris Claims with cross-file evidence.

    Returns ``(claims, original_indices, would_escalate)`` where
    ``original_indices[k]`` is the index into ``raw_debris`` of ``claims[k]`` —
    the unambiguous join used to map dismissed verdicts back to suppressions.
    ``would_escalate`` counts eligible findings the builder could not fill.
    """

    if facts_db is None:
        from .facts import FactsDB

        facts_db = FactsDB(config)
    if symbols_by_file is None:
        from .symbols import load_all_symbols

        symbols_by_file = load_all_symbols(config)

    claims: list[Claim] = []
    original_indices: list[int] = []
    would_escalate = 0

    for i, finding in enumerate(raw_debris):
        if not _is_eligible(finding):
            continue
        claim = _try_build_claim(config, finding, facts_db, symbols_by_file)
        if claim is None:
            would_escalate += 1
        else:
            claims.append(claim)
            original_indices.append(i)

    return claims, original_indices, would_escalate


def _try_build_claim(
    config: Config,
    finding: dict,
    facts_db: Any,
    symbols_by_file: dict[str, list[dict]],
) -> Claim | None:
    """Build one Claim with evidence, or None if no evidence can be gathered."""

    desc = finding.get("description", "")
    source = finding.get("source") or finding.get("source_path") or ""
    if not source:
        return None
    source = str(source)

    symbols = _extract_all_symbols_from_debris(desc)
    if not symbols:
        return None

    best_refs: list[dict] = []
    for sym in symbols:
        refs = facts_db.cross_file_references(sym, source)
        if len(refs) > len(best_refs):
            best_refs = refs

    type_defs: list[dict] = []
    if finding.get("category") == "latent_bug":
        type_names = [s for s in symbols if s and s[0].isupper() and not s.isupper()]
        inferred = _infer_variable_type(config, source, finding.get("line_start"), desc)
        type_names.extend(inferred)
        if type_names:
            type_defs = _lookup_type_definitions(config, type_names, symbols_by_file)

    if not best_refs and not type_defs:
        return None

    finding_obj = finding_from_debris(finding, root=config.root_path)
    evidence: list[Evidence] = list(finding_obj.evidence)
    if best_refs:
        shadow_excerpts: dict[str, str] = {}
        for ref in best_refs[:3]:
            shadow = load_shadow_content(config, ref["file"])
            if shadow:
                shadow_excerpts[ref["file"]] = shadow[:2000]
        evidence.append(
            Evidence(
                kind="cross_file_reference",
                payload={"references": best_refs, "shadow_excerpts": shadow_excerpts},
            )
        )
    for td in type_defs:
        evidence.append(Evidence(kind="type_signature", payload=td))

    return Claim(replace(finding_obj, evidence=evidence))


# --- relocated debris evidence helpers (verbatim from audit.py) ------------

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
