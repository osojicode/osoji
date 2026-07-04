"""Bridge from legacy per-detector outputs to the unified :class:`Finding`.

V1-2 introduces the ``Finding`` schema but does not change any detector. This
module is the bridge: pure functions that convert each detector's current native
output shape into a ``Finding`` so downstream consumers (Triage in V1-3) can be
migrated incrementally. It is **not** wired into ``audit.py``'s live path in this
PR — it is exercised by unit tests only, which is what keeps the
``prompt_regression`` baselines byte-identical.

Two design rules carried from the V1-2 plan / C&C review:

1. **Triage-output fields stay ``None``.** The spec assigns
   ``verdict``/``confidence``/``triage_reasoning``/``suggested_fix``/``severity``
   to the Triage stage. The adapter never populates them, even though every
   native type carries its own confidence/severity/remediation.
2. **Detector priors are preserved, not dropped** (signal conservation). Each
   native finding's priors are attached as a single
   ``Evidence(kind="scanner_metadata", ...)`` rather than melted into prose or
   discarded. The concrete V1-4 ``EvidenceBuilder`` machinery is not used here —
   we hand-construct the ``Evidence`` dataclass, which exists as of this PR.

``detector`` uses a uniform ``"<producer>:<category>"`` name, decoupled from
``gap_type`` and stable as the 1:1 unit for V1-7 per-detector metrics.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .evidence import Evidence
from .findings import Finding, GapType

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import-time coupling
    from .deadcode import DeadCodeCandidate
    from .deadparam import DeadParamCandidate
    from .doc_analysis import DocFinding
    from .junk import JunkFinding
    from .obligations import ContractFinding


# --- Category -> gap_type ---------------------------------------------------
#
# Built from the authoritative three-gap taxonomy (wiki concepts/three-gap-theory)
# reconciled against the categories the code *actually* emits (tools.py enums +
# the six junk analyzers). ``latent_bug`` is intentionally absent so it falls to
# the ``uncategorized`` outlet (the adapter cannot mechanically tell a stated-
# invariant violation from an implicit one). Contract findings dispatch from
# ``finding_type`` rather than ``category`` and are set directly.
CATEGORY_TO_GAP_TYPE: dict[str, GapType] = {
    # reachability
    "dead_code": "reachability",
    "dead_symbol": "reachability",
    "dead_parameter": "reachability",
    "unactuated_config": "reachability",
    "orphaned_file": "reachability",
    "dead_dependency": "reachability",
    "unused_dependency": "reachability",  # forward-compat alias; not emitted today
    "dead_cicd": "reachability",
    # description
    "stale_content": "description",
    "incorrect_content": "description",
    "misleading_claim": "description",
    "stale_comment": "description",
    "obsolete_reference": "description",
    "misleading_docstring": "description",
    "commented_out_code": "description",
    "expired_todo": "description",
    # NOTE: "latent_bug" omitted on purpose -> uncategorized.
}

# Maps a junk category to the analyzer that produces it, for the detector name.
_JUNK_PRODUCER: dict[str, str] = {
    "dead_symbol": "deadcode",
    "dead_parameter": "deadparam",
    "unactuated_config": "plumbing",
    "dead_dependency": "deps",
    "dead_cicd": "cicd",
    "orphaned_file": "orphan",
}


def gap_type_for(category: str) -> GapType:
    """Return the gap_type for a category, falling back to ``uncategorized``."""

    return CATEGORY_TO_GAP_TYPE.get(category, "uncategorized")


def _norm_path(path: str | Path, root: str | Path | None = None) -> str:
    """Normalize a path to a project-relative, forward-slash string.

    The adapter is pure (no ``Config``); native sources are usually already
    project-relative POSIX strings (FactsDB normalizes that way). If ``root`` is
    given and ``path`` is absolute, the path is made relative to it first.
    """

    p = Path(path)
    if root is not None and p.is_absolute():
        try:
            p = p.relative_to(Path(root))
        except ValueError:
            pass
    posix = PurePosixPath(str(p).replace("\\", "/")).as_posix()
    return posix[2:] if posix.startswith("./") else posix


def finding_from_junk(jf: "JunkFinding", *, root: str | Path | None = None) -> Finding:
    """Convert a :class:`osoji.junk.JunkFinding` (reachability gaps) to a Finding."""

    category = jf.category
    detector = f"{_JUNK_PRODUCER.get(category, 'junk')}:{category}"
    evidence = Evidence(
        kind="scanner_metadata",
        weight_hint=jf.confidence,
        payload={
            "remediation": jf.remediation,
            "confidence": jf.confidence,
            "confidence_source": jf.confidence_source,
            "metadata": dict(jf.metadata),
        },
    )
    return Finding(
        detector=detector,
        gap_type=gap_type_for(category),
        path=_norm_path(jf.source_path, root),
        line_start=jf.line_start,
        line_end=jf.line_end,
        symbol=jf.name,
        contract_source=jf.kind,
        contract_claim=jf.original_purpose,
        observed_behavior=jf.reason,
        evidence=[evidence],
    )


def finding_from_dead_code_candidate(
    c: "DeadCodeCandidate",
    *,
    ast_proven: bool = False,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.deadcode.DeadCodeCandidate` (V1-5a).

    Unlike :func:`finding_from_junk` (which bridges the *post-verification*
    ``JunkFinding``), this adapter runs *before* Triage: the candidate is the
    hypothesis, and the scanner's propose-time observations ride along as
    ``scanner_metadata`` for the Claim Builder. ``scan_needles`` and
    ``priority_paths`` steer :class:`~osoji.evidence_builders.CrossFileReferenceBuilder`
    (qualified + bare needles; grep-hit files swept cap-exempt).

    ``contract_claim`` interpolates only name/kind — it is hashed into
    ``finding.id``, so counts and line numbers must stay out of it.
    """

    name = c.name
    bare = name.rsplit(".", 1)[-1]
    hit_files = sorted({h.file_path for h in c.grep_hits})
    if ast_proven:
        observed = (
            "FactsDB AST graph shows zero cross-file references to the symbol; "
            "all importers of the defining file have AST-extracted facts."
        )
    elif c.ref_count == 0:
        observed = "Reference scan found no external file referencing the symbol."
    else:
        observed = (
            f"Reference scan found textual matches in {c.ref_count} external "
            "location(s) that may not be genuine usages."
        )
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "ref_count": c.ref_count,
            "kind": c.kind,
            "scan": "ast" if ast_proven else "grep",
            "hit_files": hit_files,
            "scan_needles": [name] + ([bare] if bare != name else []),
            "priority_paths": hit_files,
        },
    )
    return Finding(
        detector="deadcode:dead_symbol",
        gap_type="reachability",
        path=_norm_path(c.source_path, root),
        line_start=c.line_start,
        line_end=c.line_end,
        symbol=name,
        contract_source="symbol declaration",
        contract_claim=(
            f"Symbol `{name}` ({c.kind}) is declared as part of the file's public "
            "surface but appears unused — no genuine references outside its own "
            "declaration."
        ),
        observed_behavior=observed,
        evidence=[evidence],
    )


def finding_from_dead_param_candidate(
    c: "DeadParamCandidate",
    importers: list[str] | None = None,
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.deadparam.DeadParamCandidate` (V1-5a).

    ``symbol`` is ``function.param`` (matches the legacy ``JunkFinding.name``
    and keeps same-named params in different functions from colliding on
    ``finding.id``). The scan needles are the bare parameter name FIRST — its
    hits carry the deciding evidence (the gated branch in the defining file;
    a zero-hit at caller files is evidence the parameter is never passed,
    which the V1-4 bootstrap showed drives the verdict) — then the function's
    grep names for call-site visibility. A common param name is a noisy
    repo-wide needle, so ``priority_paths`` (defining file, observed call-site
    files, importers) are swept first and cap-exempt to keep the deciding
    sites ahead of incidental matches.
    """

    func = c.function_name
    grep_name = func.rsplit(".", 1)[-1]
    needles = [c.param_name, grep_name]
    if "." in func:
        needles.append(func.rsplit(".", 1)[0])  # constructor calls: ClassName(...)
    call_site_files = sorted({s.file_path for s in c.call_sites})
    priority: list[str] = []
    for p in [_norm_path(c.source_path, root), *call_site_files, *(importers or [])]:
        norm = _norm_path(p, root)
        if norm and norm not in priority:
            priority.append(norm)
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "function_name": func,
            "param_name": c.param_name,
            "has_default": c.has_default,
            "param_line": c.param_line,
            "n_call_sites": len(c.call_sites),
            "call_site_files": call_site_files,
            "scan_needles": needles,
            "priority_paths": priority,
        },
    )
    return Finding(
        detector="deadparam:dead_parameter",
        gap_type="reachability",
        path=_norm_path(c.source_path, root),
        line_start=c.param_line,
        line_end=c.param_line,
        symbol=f"{func}.{c.param_name}",
        contract_source="function signature",
        contract_claim=(
            f"Parameter `{c.param_name}` is declared in the signature of "
            f"`{func}` as an accepted optional input that callers may pass."
        ),
        observed_behavior=(
            f"Reference scan found {len(c.call_sites)} call site(s) of `{func}` "
            "across the defining file and its importers; the scanner does not "
            f"parse call arguments — whether any caller passes `{c.param_name}` "
            "must be judged from the call-site evidence."
        ),
        evidence=[evidence],
    )


def finding_from_contract(cf: "ContractFinding", *, root: str | Path | None = None) -> Finding:
    """Convert a :class:`osoji.obligations.ContractFinding` (contract gaps) to a Finding."""

    observed = "; ".join(f"{k}={v}" for k, v in cf.evidence.items()) if cf.evidence else cf.description
    evidence = Evidence(
        kind="scanner_metadata",
        weight_hint=cf.confidence,
        payload={
            "severity": cf.severity,
            "remediation": cf.remediation,
            "confidence": cf.confidence,
            "producer_file": cf.producer_file,
            "definer_file": cf.definer_file,
            "evidence": dict(cf.evidence),
        },
    )
    return Finding(
        detector=f"obligations:{cf.finding_type}",
        gap_type="contract",
        path=_norm_path(cf.consumer_file, root),
        line_start=None,
        line_end=None,
        symbol=cf.value,
        contract_source=cf.contract_type,
        contract_claim=cf.description,
        observed_behavior=observed,
        evidence=[evidence],
    )


def finding_from_doc(
    df: "DocFinding",
    doc_path: str | Path,
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a :class:`osoji.doc_analysis.DocFinding` (description gaps) to a Finding.

    ``doc_path`` comes from the enclosing ``DocAnalysisResult.path``.
    """

    evidence = Evidence(
        kind="scanner_metadata",
        weight_hint=0.0,  # DocFinding has no finding-level confidence
        payload={
            "severity": df.severity,
            "remediation": df.remediation,
            "search_terms": list(df.search_terms),
            "shadow_ref": df.shadow_ref,
            # The propose step's search terms double as scan needles: they steer
            # CrossFileReferenceBuilder to sweep the same identifiers the deleted
            # verify pass grepped for — the mechanized replacement for that pass's
            # project-wide evidence gathering.
            "scan_needles": list(df.search_terms),
        },
    )
    return Finding(
        detector=f"doc:{df.category}",
        gap_type=gap_type_for(df.category),
        path=_norm_path(doc_path, root),
        line_start=None,
        line_end=None,
        symbol=None,
        contract_source=df.shadow_ref or "documentation",
        contract_claim=df.description,
        observed_behavior=df.evidence,
        evidence=[evidence],
    )


def finding_from_debris(d: dict[str, Any], *, root: str | Path | None = None) -> Finding:
    """Convert a raw debris finding dict (from ``.osoji/findings/*.findings.json``).

    Categories: ``dead_code`` (reachability), ``stale_comment`` /
    ``misleading_docstring`` / ``commented_out_code`` / ``expired_todo``
    (description), ``latent_bug`` (-> uncategorized). The native shape does not
    separate the claim from the behavior, so both draw on ``description`` — a
    known bridge limitation that V1-5's native Finding emission will resolve.
    """

    category = d["category"]
    description = d["description"]
    evidence = Evidence(
        kind="scanner_metadata",
        weight_hint=0.0,  # debris findings have no finding-level confidence
        payload={
            "severity": d.get("severity"),
            "suggestion": d.get("suggestion"),
            "cross_file_verification_needed": d.get("cross_file_verification_needed", False),
        },
    )
    return Finding(
        detector=f"debris:{category}",
        gap_type=gap_type_for(category),
        path=_norm_path(str(d.get("source") or d.get("source_path") or ""), root),
        line_start=d.get("line_start"),
        line_end=d.get("line_end"),
        symbol=None,
        contract_source="code",
        contract_claim=description,
        observed_behavior=description,
        evidence=[evidence],
    )


def findings_from_debris(
    items: list[dict[str, Any]],
    *,
    root: str | Path | None = None,
) -> list[Finding]:
    """Convert a list of raw debris dicts to Findings.

    No ``valid`` filtering: ``shadow.py`` already drops ``valid: false`` findings
    at write time (``shadow.py:526``), so persisted records carry no ``valid``
    key. Re-checking it here would encode a phantom contract.
    """

    return [finding_from_debris(d, root=root) for d in items]
