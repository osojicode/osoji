"""Evaluator library for the V1-7 corpus (osojicode/work#35).

On-disk corpus-case loading, snapshot staging, claim construction,
deterministic metrics, and the LLM-orchestration layer
(:func:`evaluate_corpus`) that decides claims through unified Triage. Consumed
by ``corpus_replay.py`` (osojicode/work#67), the proctor corpus-replay
harness (osojicode/work#63), and the GEPA adapter (osojicode/work#68).

Formats this module reads and writes are documented in
``tests/fixtures/prompt_regression/README.md``:

- ``corpus-case/1`` — one directory per adjudicated case (``case.json`` +
  ``finding.json`` + ``expected.json`` + a ``source/`` snapshot with optional
  ``symbols/``/``facts/``/``shadow/`` sidecars).
- ``corpus-splits/1`` — the append-only train/val/holdout assignment file.
- ``osoji-verdict/1`` — the NDJSON record format a replay run emits: one
  verdict record per decided claim, with a ``run_meta`` trailer LAST.

Nothing here may assume a Python target or the osoji repo itself: corpus
cases carry POSIX repo-relative paths for any language, any project.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import warnings
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from osoji.claim_builder import CLAIM_BUILDER_SCHEMA_VERSION  # noqa: E402
from osoji.config import Config  # noqa: E402
from osoji.evidence_builders import BuildContext  # noqa: E402
from osoji.findings import Finding  # noqa: E402
from osoji.junk_triage import BATCH_SIZE as JUNK_BATCH_SIZE  # noqa: E402
from osoji.junk_triage import build_junk_claims, decide_junk_claims  # noqa: E402
from osoji.llm.factory import create_provider  # noqa: E402
from osoji.triage import TRIAGE_SYSTEM_PROMPT, Claim, render_triage_prompt  # noqa: E402

CORPUS_ROOT = REPO_ROOT / "tests" / "fixtures" / "prompt_regression"

CORPUS_CASE_SCHEMA = "corpus-case/1"
CORPUS_EXPECTED_SCHEMA = "corpus-expected/1"
CORPUS_SPLITS_SCHEMA = "corpus-splits/1"
VERDICT_SCHEMA = "osoji-verdict/1"


@dataclass(frozen=True)
class CorpusCase:
    """One adjudicated corpus-case/1 entry, ready to stage and replay."""

    key: str                  # "<category>/<case_dirname>", POSIX
    case_dir: Path
    category: str
    finding: Finding           # triage-output fields None
    expected_verdict: str      # "confirmed" | "dismissed"
    expected_reasoning: str
    gray: bool
    evidence_policy: str       # "rebuild" | "frozen"
    snapshot_root: Path        # case_dir itself, or resolved snapshot_ref target
    origin: dict
    source: str = "corpus"     # "corpus" | "bootstrap" (bootstrap adapter: next PR)


def _resolve_posix_ref(base: Path, posix_ref: str) -> Path:
    """Join a POSIX-separated, corpus-root-relative ref onto ``base``.

    Case files always store ``/``-separated paths regardless of platform;
    splitting on the literal separator (rather than trusting ``Path``'s
    platform-native parsing) keeps this correct on Windows.
    """

    return base.joinpath(*posix_ref.split("/"))


def load_corpus(
    corpus_root: Path = CORPUS_ROOT,
    *,
    split: str | None = None,
    splits: dict | None = None,
    only: Collection[str] = (),
    exclude_gray: bool = False,
) -> list[CorpusCase]:
    """Load accepted corpus-case/1 entries under ``corpus_root``.

    - Anything under a ``_holding/`` directory is skipped (unreviewed sweep
      output — the glob below would otherwise match it).
    - A case whose ``expected.json`` has ``accepted`` not ``True`` is skipped
      with a collected :mod:`warnings` warning, never an exception.
    - ``case.json``/``expected.json`` schema tags are validated; a mismatch
      raises :class:`ValueError` naming the offending file.
    - ``only`` restricts to the given case keys. ``exclude_gray`` drops gray
      cases. ``split`` filters by ``splits["assignments"]`` and requires
      ``splits`` to be given.
    """

    if split is not None and splits is None:
        raise ValueError("load_corpus: split filtering requires the splits argument")

    corpus_root = Path(corpus_root)
    only_set = set(only)
    assignments = (splits or {}).get("assignments", {})

    cases: list[CorpusCase] = []
    for case_json_path in sorted(corpus_root.glob("*/case_*/case.json")):
        case_dir = case_json_path.parent
        rel_dir = case_dir.relative_to(corpus_root)
        if "_holding" in rel_dir.parts:
            continue

        category = rel_dir.parts[0]
        key = rel_dir.as_posix()
        if only_set and key not in only_set:
            continue

        case_data = json.loads(case_json_path.read_text(encoding="utf-8"))
        if case_data.get("schema") != CORPUS_CASE_SCHEMA:
            raise ValueError(
                f"bad {CORPUS_CASE_SCHEMA!r} schema tag "
                f"({case_data.get('schema')!r}) in {case_json_path}"
            )

        expected_path = case_dir / "expected.json"
        expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
        if expected_data.get("schema") != CORPUS_EXPECTED_SCHEMA:
            raise ValueError(
                f"bad {CORPUS_EXPECTED_SCHEMA!r} schema tag "
                f"({expected_data.get('schema')!r}) in {expected_path}"
            )

        if expected_data.get("accepted") is not True:
            warnings.warn(
                f"load_corpus: skipping unaccepted case {key!r} "
                f"(expected.json accepted != true)",
                stacklevel=2,
            )
            continue

        gray = bool(expected_data.get("gray", False))
        if exclude_gray and gray:
            continue

        if split is not None and assignments.get(key) != split:
            continue

        finding_path = case_dir / "finding.json"
        finding = Finding.from_dict(json.loads(finding_path.read_text(encoding="utf-8")))

        snapshot_ref = case_data.get("snapshot_ref")
        snapshot_root = (
            _resolve_posix_ref(corpus_root, snapshot_ref) if snapshot_ref else case_dir
        )

        cases.append(
            CorpusCase(
                key=key,
                case_dir=case_dir,
                category=category,
                finding=finding,
                expected_verdict=expected_data["verdict"],
                expected_reasoning=expected_data.get("reasoning", ""),
                gray=gray,
                evidence_policy=case_data.get("evidence_policy", "rebuild"),
                snapshot_root=snapshot_root,
                origin=case_data.get("origin", {}),
            )
        )

    return cases


def _copy_tree(src_dir: Path, dest_dir: Path) -> None:
    """Copy every file under ``src_dir`` into ``dest_dir``, mirroring structure."""

    if not src_dir.exists():
        return
    for src_file in src_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(src_dir)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)


def stage_case(case: CorpusCase, workdir: Path) -> Config:
    """Materialize a case's snapshot as a mini-repo under ``workdir``.

    Generalizes ``test_prompt_regression._setup_case_dir``: copies
    ``snapshot_root/source/**`` to the repo root and each optional sidecar
    (``symbols/``, ``facts/``, ``shadow/``) to its ``.osoji/`` counterpart.
    The case key is sanitized (``/`` -> ``__``) into a single directory name
    so many cases can be staged side by side under one ``workdir``.

    A ``"rebuild"``-policy case whose snapshot has no ``source/`` directory
    fails loudly here (:class:`ValueError` naming the case) rather than
    silently staging an empty mini-repo that the Claim Builder would then
    rebuild evidence against nothing for. ``"frozen"``-policy cases may
    legitimately lack ``source/`` — their evidence was serialized at sweep
    time and is never rebuilt, so there is nothing to stage it against.
    """

    workdir = Path(workdir)
    target = workdir / case.key.replace("/", "__")

    source_dir = case.snapshot_root / "source"
    if case.evidence_policy == "rebuild" and not source_dir.exists():
        raise ValueError(
            f"stage_case: case {case.key!r} has evidence_policy='rebuild' but "
            f"no source/ directory under {case.snapshot_root} — cannot rebuild "
            "evidence against an empty snapshot"
        )

    _copy_tree(source_dir, target)
    for sub in ("symbols", "facts", "shadow"):
        _copy_tree(case.snapshot_root / sub, target / ".osoji" / sub)

    return Config(root_path=target, respect_gitignore=False)


def build_case_claim(case: CorpusCase, config: Config) -> Claim:
    """Build the :class:`Claim` for a case under its declared evidence policy.

    ``"rebuild"`` reruns the mechanized Claim Builder against the staged
    snapshot (``config`` must point at a :func:`stage_case` result). ``"frozen"``
    wraps the finding as-is — its evidence was serialized at sweep time and is
    replayed unchanged, mirroring how :func:`osoji.claim_builder.build_claims`
    wraps a Finding into a Claim.
    """

    if case.evidence_policy == "rebuild":
        ctx = BuildContext(config)
        return build_junk_claims([case.finding], ctx)[0]
    if case.evidence_policy == "frozen":
        return Claim(finding=case.finding)
    raise ValueError(
        f"unknown evidence_policy {case.evidence_policy!r} for case {case.key!r}"
    )


# ---------------------------------------------------------------------------
# Variants (osojicode/work#67)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    """A named system-prompt variant a replay run decides claims under."""

    name: str
    system_prompt: str
    prompt_source: str  # "@default" | "@omit:a,b" | a file path

    @property
    def prompt_sha256(self) -> str:
        """Sha256 hexdigest of ``system_prompt`` — this variant's run_meta identity."""

        return hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()


def resolve_variant(spec: str) -> Variant:
    """Parse one ``name=value`` ``--variant`` spec into a :class:`Variant`.

    ``value`` selects the system prompt:

    - ``@default`` — :data:`osoji.triage.TRIAGE_SYSTEM_PROMPT` verbatim.
    - ``@omit:section1,section2`` — :func:`osoji.triage.render_triage_prompt`
      with those rubric sections dropped; an unknown section name's
      :class:`ValueError` propagates unchanged.
    - anything else — read as a UTF-8 file path.

    A spec with no ``=`` (a bare name) raises :class:`ValueError`. Duplicate
    variant names across a run are the caller's responsibility to reject.
    """

    if "=" not in spec:
        raise ValueError(
            f"invalid --variant spec {spec!r}: expected 'name=value' "
            "(value is @default, @omit:section1,section2, or a file path)"
        )
    name, value = spec.split("=", 1)
    if not name:
        raise ValueError(f"invalid --variant spec {spec!r}: empty variant name")

    if value == "@default":
        return Variant(name=name, system_prompt=TRIAGE_SYSTEM_PROMPT, prompt_source=value)
    if value.startswith("@omit:"):
        sections = [s for s in value[len("@omit:"):].split(",") if s]
        return Variant(
            name=name,
            system_prompt=render_triage_prompt(omit=sections),
            prompt_source=value,
        )

    prompt_text = Path(value).read_text(encoding="utf-8")
    return Variant(name=name, system_prompt=prompt_text, prompt_source=value)


# ---------------------------------------------------------------------------
# Bootstrap adapter (osojicode/work#67)
# ---------------------------------------------------------------------------


def cases_from_bootstrap_manifest(path: Path) -> list[CorpusCase]:
    """Wrap ``triage_bootstrap.py``'s manifest entries as :class:`CorpusCase`.

    The bootstrap set (``tests/fixtures/bootstrap/manifest.json``, format
    documented at the top of ``scripts/triage_bootstrap.py``) replays against
    the live repo tree, not an isolated snapshot — its findings reference the
    repo directly (see :func:`evaluate_corpus`'s staging rules). Every entry
    becomes a ``source="bootstrap"``, ``evidence_policy="rebuild"`` case with
    ``snapshot_root=REPO_ROOT`` and ``key`` set to the entry's ``slug``.
    Parsing is delegated entirely to ``triage_bootstrap.load_manifest`` — not
    reimplemented here.
    """

    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from triage_bootstrap import load_manifest  # noqa: E402, PLC0415

    manifest = load_manifest(Path(path))
    cases: list[CorpusCase] = []
    for entry in manifest["entries"]:
        cases.append(
            CorpusCase(
                key=entry["slug"],
                case_dir=REPO_ROOT,
                category=entry["category"],
                finding=Finding.from_dict(entry["finding"]),
                expected_verdict=entry["adjudicated_verdict"],
                expected_reasoning=entry.get("adjudication_notes", ""),
                gray=bool(entry.get("gray", False)),
                evidence_policy="rebuild",
                snapshot_root=REPO_ROOT,
                origin={},
                source="bootstrap",
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _producer(detector: str) -> str:
    """The producer half of a ``"<producer>:<category>"`` detector string."""

    return detector.split(":", 1)[0]


def _ranges_overlap(
    a_start: int | None, a_end: int | None, b_start: int | None, b_end: int | None
) -> bool:
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    return max(a_start, b_start) <= min(a_end, b_end)


def _me_overlap(cases: list[CorpusCase]) -> float:
    """Fraction of findings that share a symbol or line range with a
    different-producer finding in the same file (multiple-evidence overlap)."""

    findings = [c.finding for c in cases]
    total = len(findings)
    if total == 0:
        return 0.0

    by_path: dict[str, list[int]] = {}
    for i, finding in enumerate(findings):
        by_path.setdefault(finding.path, []).append(i)

    parent = list(range(total))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for indices in by_path.values():
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i, j = indices[a], indices[b]
                fi, fj = findings[i], findings[j]
                if _producer(fi.detector) == _producer(fj.detector):
                    continue
                same_symbol = fi.symbol is not None and fi.symbol == fj.symbol
                if same_symbol or _ranges_overlap(
                    fi.line_start, fi.line_end, fj.line_start, fj.line_end
                ):
                    union(i, j)

    group_producers: dict[int, set[str]] = {}
    group_members: dict[int, list[int]] = {}
    for i in range(total):
        root = find(i)
        group_producers.setdefault(root, set()).add(_producer(findings[i].detector))
        group_members.setdefault(root, []).append(i)

    overlapping = sum(
        len(group_members[root])
        for root, producers in group_producers.items()
        if len(producers) >= 2
    )
    return overlapping / total


def _rate(records: list[dict], denom_pred, numer_pred) -> float:
    denom = [r for r in records if denom_pred(r)]
    if not denom:
        return 0.0
    numer = [r for r in denom if numer_pred(r)]
    return len(numer) / len(denom)


def compute_metrics(records: list[dict], cases: list[CorpusCase]) -> dict:
    """Compute the flat metrics dict over a run's verdict records and its cases.

    ``records`` are ``osoji-verdict/1`` verdict-record dicts (see the README);
    ``cases`` is the loaded corpus the run replayed. ``tp_rate``, ``fp_rate``,
    and ``accuracy_nongray`` exclude gray cases; the remaining metrics do not
    (``ce_gap_gap_type`` and ``me_overlap`` are computed statically from
    ``cases``, independent of any particular run).
    """

    nongray = [r for r in records if not r.get("gray")]

    def is_confirmed(r: dict) -> bool:
        return r.get("verdict") == "confirmed"

    tp_rate = _rate(nongray, lambda r: r.get("expected_verdict") == "confirmed", is_confirmed)
    fp_rate = _rate(nongray, lambda r: r.get("expected_verdict") == "dismissed", is_confirmed)

    detectors = sorted({r.get("detector") for r in nongray if r.get("detector")})
    tp_rate_by_detector = {
        d: _rate(
            [r for r in nongray if r.get("detector") == d],
            lambda r: r.get("expected_verdict") == "confirmed",
            is_confirmed,
        )
        for d in detectors
    }
    fp_rate_by_detector = {
        d: _rate(
            [r for r in nongray if r.get("detector") == d],
            lambda r: r.get("expected_verdict") == "dismissed",
            is_confirmed,
        )
        for d in detectors
    }

    decided_nongray = [r for r in nongray if r.get("verdict") is not None]
    accuracy_nongray = (
        sum(1 for r in decided_nongray if r.get("verdict") == r.get("expected_verdict"))
        / len(decided_nongray)
        if decided_nongray
        else 0.0
    )

    ce_gap_gap_type = (
        sum(1 for c in cases if c.finding.gap_type == "uncategorized") / len(cases)
        if cases
        else 0.0
    )

    decided_contract = [
        r for r in records if r.get("gap_type") == "contract" and r.get("verdict") is not None
    ]
    ce_gap_contract_other = (
        sum(1 for r in decided_contract if r.get("contract_class") == "other")
        / len(decided_contract)
        if decided_contract
        else 0.0
    )

    me_overlap = _me_overlap(cases)

    rebuild_records = [r for r in records if r.get("evidence_policy") == "rebuild"]
    escalation_denominator = len(rebuild_records)
    escalation_rate = (
        sum(1 for r in rebuild_records if r.get("insufficient_evidence"))
        / escalation_denominator
        if escalation_denominator
        else 0.0
    )

    n_records = len(records)
    uncertain_rate = (
        sum(1 for r in records if r.get("verdict") == "uncertain") / n_records
        if n_records
        else 0.0
    )
    undecided_rate = (
        sum(1 for r in records if r.get("verdict") is None) / n_records if n_records else 0.0
    )

    gray_count = sum(1 for c in cases if c.gray)
    n_cases = len(cases)
    n_cases_by_category: dict[str, int] = {}
    for c in cases:
        n_cases_by_category[c.category] = n_cases_by_category.get(c.category, 0) + 1

    return {
        "tp_rate": tp_rate,
        "tp_rate_by_detector": tp_rate_by_detector,
        "fp_rate": fp_rate,
        "fp_rate_by_detector": fp_rate_by_detector,
        "accuracy_nongray": accuracy_nongray,
        "ce_gap_gap_type": ce_gap_gap_type,
        "ce_gap_contract_other": ce_gap_contract_other,
        "me_overlap": me_overlap,
        "escalation_rate": escalation_rate,
        "escalation_denominator": escalation_denominator,
        "uncertain_rate": uncertain_rate,
        "undecided_rate": undecided_rate,
        "gray_count": gray_count,
        "n_cases": n_cases,
        "n_cases_by_category": n_cases_by_category,
    }


def check_thresholds(metrics: dict, baseline: dict) -> list[str]:
    """Compare a ``compute_metrics``-shaped dict against a pinned baseline.

    ``baseline`` is an ``evaluate-baseline.json``-shaped mapping of metric
    name to ``{"max": <value>}`` and/or ``{"min": <value>}`` (both may be
    given for one metric). Returns a list of human-readable violation
    strings — empty means every bounded, comparable metric passed.

    Two things are deliberately tolerant rather than raising, so this same
    function serves both a full post-run ``metrics`` dict (every key
    ``compute_metrics`` produces) and a partial one (e.g. the static-only
    ``{ce_gap_gap_type, me_overlap}`` subset the structural corpus tests
    compute without any verdict records):

    - A baseline metric name absent from ``metrics`` is skipped — a
      threshold can only be enforced against a metric that was actually
      computed for this call.
    - A metric whose value isn't a plain ``int``/``float`` (e.g. the nested
      ``tp_rate_by_detector`` dict, or a ``bool`` masquerading as an int) is
      skipped — bounds compare scalars only.
    """

    violations: list[str] = []
    for name, bounds in baseline.items():
        if name not in metrics:
            continue
        value = metrics[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue

        if "max" in bounds and value > bounds["max"]:
            violations.append(f"{name}={value!r} exceeds max {bounds['max']!r}")
        if "min" in bounds and value < bounds["min"]:
            violations.append(f"{name}={value!r} below min {bounds['min']!r}")

    return violations


# ---------------------------------------------------------------------------
# osoji-verdict/1 NDJSON
# ---------------------------------------------------------------------------


def write_verdict_ndjson(records: list[dict], run_meta: dict, out: Path | str | TextIO) -> None:
    """Write verdict records then the ``run_meta`` trailer, one JSON object per line.

    ``out`` may be a path (opened here with strict UTF-8, no-BOM, bare-``\\n``
    settings) or an already-open text stream, which is written to directly.
    The ``run_meta`` record is always written LAST.
    """

    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    lines.append(json.dumps(run_meta, ensure_ascii=False))
    content = "\n".join(lines) + "\n"

    if isinstance(out, (str, Path)):
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    else:
        out.write(content)


def read_verdict_ndjson(path: Path) -> tuple[list[dict], dict]:
    """Read an ``osoji-verdict/1`` NDJSON file, validating schema tags.

    Returns ``(records, run_meta)``. Raises :class:`ValueError` if the file is
    empty, any line fails to parse, any record's schema/record tags are wrong,
    or the last line is not a valid ``run_meta`` trailer.
    """

    path = Path(path)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"empty verdict NDJSON: {path}")

    *record_lines, trailer_line = lines
    trailer = json.loads(trailer_line)
    if trailer.get("schema") != VERDICT_SCHEMA or trailer.get("record") != "run_meta":
        raise ValueError(
            f"verdict NDJSON missing a valid run_meta trailer as its last line: {path}"
        )

    records: list[dict] = []
    for i, line in enumerate(record_lines):
        record = json.loads(line)
        if record.get("schema") != VERDICT_SCHEMA or record.get("record") != "verdict":
            raise ValueError(f"bad verdict record schema/record tag at line {i + 1}: {path}")
        records.append(record)

    return records, trailer


# ---------------------------------------------------------------------------
# corpus-splits/1
# ---------------------------------------------------------------------------


def load_splits(path: Path) -> dict:
    """Load and validate a ``corpus-splits/1`` file."""

    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != CORPUS_SPLITS_SCHEMA:
        raise ValueError(
            f"bad {CORPUS_SPLITS_SCHEMA!r} schema tag ({data.get('schema')!r}) in {path}"
        )
    return data


def suggest_split(case_key: str, seed: int, ratios: dict[str, float]) -> str:
    """Deterministically bucket ``case_key`` into one of ``ratios``' names.

    ``sha256(f"{seed}:{case_key}")`` maps the key to a uniform ``[0, 1)``
    fraction; ``ratios`` (in the order given) partitions that range. Humans
    may override the suggestion for balance — this is only the default.
    """

    digest = hashlib.sha256(f"{seed}:{case_key}".encode("utf-8")).hexdigest()
    fraction = int(digest[:16], 16) / float(1 << 64)

    total = sum(ratios.values())
    cumulative = 0.0
    names = list(ratios.keys())
    for name in names:
        cumulative += ratios[name] / total
        if fraction < cumulative:
            return name
    return names[-1]


# ---------------------------------------------------------------------------
# GEPA gate (osojicode/work#68)
# ---------------------------------------------------------------------------


@dataclass
class GateReport:
    """Whether the corpus has enough adjudicated, split-covered cases to
    support a GEPA optimization run."""

    nongray_count: int
    required: int
    splits_nonempty: bool
    coverage_ok: bool
    missing_from_splits: list[str]
    extra_in_splits: list[str]
    passed: bool


def check_gepa_gate(cases: list[CorpusCase], splits: dict, *, required: int = 90) -> GateReport:
    """Check the V1-7 GEPA pilot gate over ``cases`` and a loaded ``splits.json``.

    Passes when all three hold: ``nongray_count >= required``;
    ``splits["assignments"]`` is non-empty; and coverage is exact — every
    case key has an assignment (``missing_from_splits`` empty) and no
    assignment names a case key that isn't in ``cases`` (``extra_in_splits``
    empty, catching stale entries left behind by a removed/renamed case).
    """

    nongray_count = sum(1 for c in cases if not c.gray)
    assignments = (splits or {}).get("assignments", {})
    splits_nonempty = bool(assignments)

    case_keys = {c.key for c in cases}
    assignment_keys = set(assignments)
    missing_from_splits = sorted(case_keys - assignment_keys)
    extra_in_splits = sorted(assignment_keys - case_keys)
    coverage_ok = not missing_from_splits and not extra_in_splits

    passed = nongray_count >= required and splits_nonempty and coverage_ok
    return GateReport(
        nongray_count=nongray_count,
        required=required,
        splits_nonempty=splits_nonempty,
        coverage_ok=coverage_ok,
        missing_from_splits=missing_from_splits,
        extra_in_splits=extra_in_splits,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# Orchestration (osojicode/work#67)
# ---------------------------------------------------------------------------


@dataclass
class EvalRun:
    """A completed replay: decided verdict records plus their run_meta trailer."""

    records: list[dict]
    run_meta: dict


def default_run_id() -> str:
    """The default ``--run-id``: ``eval-YYYYMMDD-<8hex>``."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"eval-{stamp}-{secrets.token_hex(4)}"


def _git_commit() -> str:
    """Best-effort ``git rev-parse HEAD`` at :data:`REPO_ROOT`; ``"unknown"`` on failure."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — best-effort provenance, never fatal
        return "unknown"


def _stage_and_build_claims(cases: list[CorpusCase], workdir: Path) -> list[Claim]:
    """Stage each case per its source's semantics and build its claim.

    ``source == "corpus"`` cases are copied into ``workdir`` via
    :func:`stage_case` (an isolated snapshot per case). ``source ==
    "bootstrap"`` cases are NOT copied — they replay against the live repo
    tree (one shared ``Config(root_path=REPO_ROOT, respect_gitignore=False)``
    for all of them), matching that corpus's documented semantics. Claims are
    built once per case, independent of variant or repeat: only the decide
    pass depends on the prompt.
    """

    claims: list[Claim] = []
    bootstrap_config: Config | None = None
    for case in cases:
        if case.source == "corpus":
            config = stage_case(case, workdir)
        elif case.source == "bootstrap":
            if bootstrap_config is None:
                bootstrap_config = Config(root_path=REPO_ROOT, respect_gitignore=False)
            config = bootstrap_config
        else:
            raise ValueError(f"unknown case source {case.source!r} for case {case.key!r}")
        claims.append(build_case_claim(case, config))
    return claims


def _build_verdict_record(
    *, run_id: str, variant_name: str, repeat: int, case: CorpusCase, claim: Claim, finding: Finding
) -> dict:
    """Build one ``osoji-verdict/1`` verdict record (README field table)."""

    verdict = finding.verdict
    correct = None if verdict is None else (verdict == case.expected_verdict)
    return {
        "schema": VERDICT_SCHEMA,
        "record": "verdict",
        "run_id": run_id,
        "variant": variant_name,
        "repeat": repeat,
        "source": case.source,
        "case": case.key,
        "finding_id": finding.id,
        "detector": finding.detector,
        "category": case.category,
        "gap_type": finding.gap_type,
        "path": finding.path,
        "symbol": finding.symbol,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "expected_verdict": case.expected_verdict,
        "gray": case.gray,
        "verdict": verdict,
        "confidence": finding.confidence,
        "severity": finding.severity,
        "contract_class": finding.contract_class,
        "triage_reasoning": finding.triage_reasoning,
        "suggested_fix": finding.suggested_fix,
        "insufficient_evidence": claim.insufficient_evidence,
        "evidence_policy": case.evidence_policy,
        "correct": correct,
    }


async def evaluate_corpus(
    cases: list[CorpusCase],
    variants: list[Variant],
    *,
    repeats: int = 1,
    repeat_offset: int = 0,
    run_id: str | None = None,
    provider: Any | None = None,
    config_factory: Callable[[], Config] | None = None,
    batch_size: int | None = None,
    workdir: Path,
    corpus_root: Path | str | None = None,
    split: str | None = None,
    only: Collection[str] = (),
    exclude_gray: bool = False,
) -> EvalRun:
    """Replay ``cases`` through Triage under each variant, ``repeats`` times each.

    One :func:`osoji.junk_triage.decide_junk_claims` pass per ``(variant,
    repeat)`` pair, over every case's claim together — production-shaped
    batching (``BATCH_SIZE`` chunking, bisect retry on chunk failure), never
    a per-case loop. Claims are built once, before any variant runs (evidence
    does not depend on the prompt); see :func:`_stage_and_build_claims` for
    how each case is staged per its ``source``.

    Cases of both sources may be mixed in one call. The ``config`` argument
    ``decide_junk_claims`` receives only governs the model it requests:
    reading ``Triage.decide_batch``'s claim-mode route shows it calls
    ``self.config.model_for("medium")`` and nothing else on ``config`` — no
    filesystem access, no ``root_path`` — so a single shared *runtime*
    config (built by ``config_factory``, separate from each case's staging
    config) can safely govern one decide pass across every case regardless
    of source. ``escalate_insufficient`` is never set: ``decide_junk_claims``
    always calls ``decide_batch`` with its default (``False``), so
    insufficient-evidence claims pass through with ``verdict=None`` rather
    than escalating to exploration — matching production debris-path
    behaviour.

    ``provider=None`` builds one via :func:`osoji.llm.factory.create_provider`
    (the same factory the prompt-regression tests call directly) against the
    runtime config's resolved provider name, and closes it when the run
    finishes; an injected ``provider`` (always the case in tests) is never
    closed here — the caller owns it. Staging happens BEFORE this
    construction: a provider we own opens an async client on construction, so
    a staging failure (e.g. :func:`stage_case`'s ``ValueError`` for a
    rebuild-policy case with no ``source/``) must not have anything open yet
    to leak; the owned provider's try/finally then covers its entire
    lifetime, from construction to close. ``config_factory`` defaults to
    ``Config(root_path=REPO_ROOT, respect_gitignore=False)``.

    Token totals: ``decide_junk_claims`` returns ``(findings, input_tokens,
    output_tokens)`` directly, the same tuple ``audit.py``'s
    ``_run_phase3_async``/``_run_phase3_5_async`` unpack to tally their
    ``phase_tokens`` — so summing that return value across every ``(variant,
    repeat)`` call *is* the production accounting; no separate seam or
    rate-limiter reach-through was needed.

    ``corpus_root``/``split``/``only``/``exclude_gray`` are passed through
    verbatim into ``run_meta["corpus"]`` for provenance (mirroring
    :func:`load_corpus`'s own parameters) — ``evaluate_corpus`` itself only
    computes ``n_cases``/``n_gray`` from ``cases``.

    Raises :class:`ValueError` if ``cases`` or ``variants`` is empty.
    """

    if not cases:
        raise ValueError("evaluate_corpus: cases is empty")
    if not variants:
        raise ValueError("evaluate_corpus: variants is empty")

    resolved_run_id = run_id or default_run_id()
    workdir = Path(workdir)
    effective_batch_size = batch_size if batch_size is not None else JUNK_BATCH_SIZE

    runtime_config = (
        config_factory()
        if config_factory is not None
        else Config(root_path=REPO_ROOT, respect_gitignore=False)
    )

    started_at = datetime.now(timezone.utc)
    # Stage BEFORE constructing a provider: a provider (when we own it) opens
    # an async client on construction, so if staging raises — e.g. stage_case's
    # ValueError for a rebuild-policy case with no source/ — nothing has been
    # opened yet and there is nothing to leak. The provider's try/finally below
    # starts immediately at construction, covering its entire owned lifetime.
    claims = _stage_and_build_claims(cases, workdir)

    owns_provider = provider is None
    active_provider = (
        provider
        if provider is not None
        else create_provider(runtime_config.provider or "anthropic")
    )

    records: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    try:
        for variant in variants:
            for k in range(repeats):
                findings, in_tok, out_tok = await decide_junk_claims(
                    claims,
                    runtime_config,
                    active_provider,
                    batch_size=effective_batch_size,
                    system_prompt=variant.system_prompt,
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                repeat_index = repeat_offset + k
                for case, claim, finding in zip(cases, claims, findings):
                    records.append(
                        _build_verdict_record(
                            run_id=resolved_run_id,
                            variant_name=variant.name,
                            repeat=repeat_index,
                            case=case,
                            claim=claim,
                            finding=finding,
                        )
                    )
    finally:
        if owns_provider:
            await active_provider.close()

    finished_at = datetime.now(timezone.utc)

    run_meta = {
        "schema": VERDICT_SCHEMA,
        "record": "run_meta",
        "run_id": resolved_run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "variants": {
            v.name: {"prompt_sha256": v.prompt_sha256, "prompt_source": v.prompt_source}
            for v in variants
        },
        "provider": runtime_config.provider,
        "model": runtime_config.model_for("medium"),
        "osoji_commit": _git_commit(),
        "claim_builder_schema_version": CLAIM_BUILDER_SCHEMA_VERSION,
        "corpus": {
            "root": str(corpus_root) if corpus_root is not None else None,
            "n_cases": len(cases),
            "n_gray": sum(1 for c in cases if c.gray),
            "split": split,
            "only": sorted(only) if only else None,
            "exclude_gray": exclude_gray,
        },
        "repeats": repeats,
        "repeat_offset": repeat_offset,
        "batch_size": effective_batch_size,
        "tokens": {"input": total_input_tokens, "output": total_output_tokens},
        "metrics": compute_metrics(records, cases),
    }

    return EvalRun(records=records, run_meta=run_meta)


def select_cases(
    *,
    source: str,
    corpus_root: Path = CORPUS_ROOT,
    bootstrap_manifest: Path | None = None,
    split: str | None = None,
    splits: dict | None = None,
    only: Collection[str] = (),
    exclude_gray: bool = False,
) -> list[CorpusCase]:
    """Resolve a CLI-style case selection across one or both sources.

    ``source`` is ``"corpus"``, ``"bootstrap"``, or ``"both"``. ``only`` and
    ``exclude_gray`` apply uniformly to whichever sources are selected
    (matched against a bootstrap case's ``key``, its manifest ``slug``).
    ``split``/``splits`` only apply to the corpus source — bootstrap
    manifests carry no split assignments — and are passed through to
    :func:`load_corpus` unchanged.
    """

    if source not in ("corpus", "bootstrap", "both"):
        raise ValueError(f"select_cases: unknown source {source!r}")

    cases: list[CorpusCase] = []
    if source in ("corpus", "both"):
        cases.extend(
            load_corpus(
                corpus_root, split=split, splits=splits, only=only, exclude_gray=exclude_gray
            )
        )
    if source in ("bootstrap", "both"):
        if bootstrap_manifest is None:
            raise ValueError(f"select_cases: source={source!r} requires bootstrap_manifest")
        bootstrap_cases = cases_from_bootstrap_manifest(bootstrap_manifest)
        only_set = set(only)
        if only_set:
            bootstrap_cases = [c for c in bootstrap_cases if c.key in only_set]
        if exclude_gray:
            bootstrap_cases = [c for c in bootstrap_cases if not c.gray]
        cases.extend(bootstrap_cases)

    return cases
