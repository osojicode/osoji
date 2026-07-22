"""Bridge from per-detector native outputs to the unified :class:`Finding`.

This module is on the live audit path: every detector's native output shape
converts to a ``Finding`` here before the Claim Builder gathers evidence and
Triage decides. The adapters are pure functions, exercised both by the audit
orchestrator and directly by unit tests.

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
    from .junk_cicd import CICDCandidate
    from .junk_deps import DependencyCandidate
    from .junk_orphan import OrphanCandidate
    from .obligations import ContractFinding
    from .plumbing import ConfigObligation

# Cap on detector-supplied scan needles (matches the Claim Builder's own
# ``_MAX_NEEDLES`` — the builder trims to the same bound, so trimming here keeps
# the persisted metadata honest about what the sweep will actually grep for).
_MAX_NEEDLES = 5


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
    # contract — persisted obligations categories are prefixed
    # ``obligation_{finding_type}`` (audit.py), so the persisted-category
    # consumer routes them to the contract gap rather than ``uncategorized``.
    "obligation_violation": "contract",
    "obligation_implicit_contract": "contract",
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


def _dedup_needles(names: list[str], *, cap: int = _MAX_NEEDLES) -> list[str]:
    """Order-preserving dedup of non-empty needle strings, capped at ``cap``."""

    out: list[str] = []
    for name in names:
        if name and name not in out:
            out.append(name)
        if len(out) >= cap:
            break
    return out


def finding_from_config_obligation(
    o: "ConfigObligation",
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.plumbing.ConfigObligation` (V1-5b).

    The candidate is the hypothesis "this schema field declares an obligation the
    system never enforces". The scan needles are the field name FIRST — its
    same-file hit is the gated definition, and zero hits at consumer files is the
    never-actuated signal — then the schema/class name. The claim is framed in
    *enforcement* terms so the unified reachability rubric judges actuation
    (a store/pass/log reference is a real use in the sweep sense but does NOT
    enforce), not mere textual reference.
    """

    field_name = o.field_name
    schema_name = o.schema_name
    needles = _dedup_needles([field_name] + ([schema_name] if schema_name else []))
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "schema_name": schema_name,
            "field_name": field_name,
            "line_start": o.line_start,
            "line_end": o.line_end,
            "obligation": o.obligation,
            "expected_actuation": o.expected_actuation,
            "scan_needles": needles,
            "priority_paths": [],
        },
    )
    return Finding(
        detector="plumbing:unactuated_config",
        gap_type="reachability",
        path=_norm_path(o.source_path, root),
        line_start=o.line_start,
        line_end=o.line_end,
        symbol=field_name,
        contract_source="config schema field",
        contract_claim=(
            f"Field `{field_name}` (schema `{schema_name}`) declares an obligation "
            f"the system must enforce at runtime: {o.obligation}. Expected "
            f"enforcement: {o.expected_actuation}."
        ),
        observed_behavior=(
            "Reference scan gathers where the field is read across the repo; a site "
            "that only stores, passes, restructures, or logs the value does not "
            "enforce it — actuation requires code that uses it to cause the declared "
            "effect."
        ),
        evidence=[evidence],
    )


def finding_from_orphan_candidate(
    c: "OrphanCandidate",
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.junk_orphan.OrphanCandidate` (V1-5b).

    ``symbol`` is the bare filename (matches the legacy ``JunkFinding.name``). The
    scan needles are the file's basename and stem FIRST (string/import references),
    then its exported symbol names from ``public_surface`` (secondary
    import-reference needles). Language-agnostic: every needle is a string drawn
    from the candidate's own data — no "looks like a module" heuristic. An orphan
    has no known importers by construction, so ``priority_paths`` is empty; the
    repo sweep is what catches dynamic/config/CI string references the import-edge
    graph missed.
    """

    # Normalize to forward slashes first: a bare ``Path(...).name``/``.stem`` only
    # splits on the host OS's separator, so a backslash-separated path surviving
    # from a Windows-walked repo would silently fail to split on Linux/macOS.
    norm_source_path = PurePosixPath(c.source_path.replace("\\", "/"))
    basename = norm_source_path.name
    stem = norm_source_path.stem
    needles = _dedup_needles([basename, stem] + list(c.public_surface))
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "source_path": c.source_path,
            "file_role": c.file_role,
            "purpose": c.purpose,
            "topics": list(c.topics),
            "public_surface": list(c.public_surface),
            "scan_needles": needles,
            "priority_paths": [],
        },
    )
    return Finding(
        detector="orphan:orphaned_file",
        gap_type="reachability",
        path=_norm_path(c.source_path, root),
        line_start=1,
        line_end=None,
        symbol=basename,
        contract_source="project file",
        contract_claim=(
            f"File `{c.source_path}` (role: {c.file_role}; purpose: {c.purpose}) is "
            "part of the project but no entry point reaches it via the import graph."
        ),
        observed_behavior=(
            "Reference scan sweeps the repo for the file's name and exported symbols; "
            "hits (dynamic import, config/CI reference, convention loader) show it is "
            "still reached, while zero hits over a real scan scope support the orphan "
            "verdict."
        ),
        evidence=[evidence],
    )


def finding_from_dep_candidate(
    c: "DependencyCandidate",
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.junk_deps.DependencyCandidate` (V1-5b).

    Adapts from a *genuine* zero-import candidate (build tools / plugins / type
    stubs already filtered upstream by the retained classify stage). The scan
    needles are the declared package name AND every resolved import name (the
    resolve-imports stage output, e.g. pillow -> PIL). ``priority_paths`` is empty:
    a genuine candidate has ``import_hits == 0`` so there are no pre-known hit
    files; the reference sweep gathers any non-import textual use.
    """

    needles = _dedup_needles([c.package_name] + list(c.import_names))
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "package_name": c.package_name,
            "import_names": list(c.import_names),
            "is_dev": c.is_dev,
            "ecosystem": c.ecosystem,
            "line_number": c.line_number,
            "scan_needles": needles,
            "priority_paths": [],
        },
    )
    return Finding(
        detector="deps:dead_dependency",
        gap_type="reachability",
        path=_norm_path(c.manifest_path, root),
        line_start=c.line_number,
        line_end=None,
        symbol=c.package_name,
        contract_source="dependency manifest",
        contract_claim=(
            f"Package `{c.package_name}` is declared as a"
            f"{' dev' if c.is_dev else ''} dependency in `{c.manifest_path}` "
            f"(import names: {list(c.import_names)})."
        ),
        observed_behavior=(
            "Import scan found zero import matches; the reference sweep gathers any "
            "non-import textual use (config files, scripts) so the LLM can judge "
            "build-tool/plugin/CLI liveness before confirming dead."
        ),
        evidence=[evidence],
    )


def finding_from_cicd_candidate(
    c: "CICDCandidate",
    *,
    root: str | Path | None = None,
) -> Finding:
    """Convert a propose-time :class:`osoji.junk_cicd.CICDCandidate` (V1-5b).

    The scan needles are the element/job/target name FIRST (catches another
    target/job that depends on this one — the "used as a dependency" alive signal),
    then the basenames of the referenced (missing) paths the element points at.
    ``element_content`` is not carried in the metadata: the ``SurroundingCodeBuilder``
    re-reads the flagged region from ``cicd_file`` (which is read directly, not via
    the corpus, so the ``.github`` exclusion does not hide it).
    """

    missing_names = [PurePosixPath(p).name for p in c.missing_paths]
    needles = _dedup_needles([c.element_name] + missing_names)
    evidence = Evidence(
        kind="scanner_metadata",
        payload={
            "element_name": c.element_name,
            "element_type": c.element_type,
            "line_start": c.line_start,
            "line_end": c.line_end,
            "missing_paths": list(c.missing_paths),
            "scan_needles": needles,
            "priority_paths": [],
        },
    )
    return Finding(
        detector="cicd:dead_cicd",
        gap_type="reachability",
        path=_norm_path(c.cicd_file, root),
        line_start=c.line_start,
        line_end=c.line_end,
        symbol=c.element_name,
        contract_source="CI/CD element",
        contract_claim=(
            f"{c.element_type} `{c.element_name}` in `{c.cicd_file}` references "
            f"path(s) {list(c.missing_paths)} that no longer exist in the repo."
        ),
        observed_behavior=(
            "Path-existence check already found the referenced paths missing; the "
            "reference sweep gathers repo mentions of the element name and script "
            "names so the LLM can judge external-target / dynamic-discovery / "
            "phony-target liveness (missing paths are the primary but not "
            "dispositive signal)."
        ),
        evidence=[evidence],
    )


def finding_from_contract(cf: "ContractFinding", *, root: str | Path | None = None) -> Finding:
    """Convert a :class:`osoji.obligations.ContractFinding` (contract gaps) to a Finding.

    The detector name is prefixed (``obligations:obligation_{finding_type}``) so
    ``category_of`` matches both the ``CLAIM_BUILDER_SCHEMA`` obligation_* keys and
    the persisted ``obligation_{finding_type}`` category — one canonical namespace.

    ``scan_needles`` (the shared literal value(s)) and ``priority_paths`` (the
    file tuple: consumer/producer/definer plus every co-sharer) steer the
    :class:`~osoji.evidence_builders.CrossFileReferenceBuilder` so it sweeps both
    sides of the contract cap-exempt — the file-tuple minimum context, mechanized
    (previously the LLM ran this grep-set by hand).
    """

    observed = "; ".join(f"{k}={v}" for k, v in cf.evidence.items()) if cf.evidence else cf.description
    needles = [cf.value] if cf.value else list(cf.evidence.get("values", []))
    # The full file tuple; drop the violations' "(no producer found)" sentinel
    # and any absent definer, normalize, and dedupe (consumer first — it anchors).
    priority_paths: list[str] = []
    for p in (
        cf.consumer_file,
        cf.producer_file,
        cf.definer_file,
        *cf.evidence.get("producer_files", ()),
        *cf.evidence.get("checker_files", ()),
        *cf.evidence.get("definer_files", ()),
    ):
        if not p or p == "(no producer found)":
            continue
        norm = _norm_path(p, root)
        if norm and norm not in priority_paths:
            priority_paths.append(norm)
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
            "scan_needles": needles,
            "priority_paths": priority_paths,
        },
    )
    return Finding(
        detector=f"obligations:obligation_{cf.finding_type}",
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
