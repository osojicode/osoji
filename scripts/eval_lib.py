"""Evaluator library for the V1-7 corpus (osojicode/work#35).

Mechanical core only: on-disk corpus-case loading, snapshot staging, claim
construction, and deterministic metrics over a batch of verdict records. No
LLM orchestration lives here — that is the next PR's ``corpus_replay.py``
(osojicode/work#67). Consumed by ``corpus_replay.py``, the proctor
corpus-replay harness (osojicode/work#63), and the GEPA adapter
(osojicode/work#68).

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
import shutil
import sys
import warnings
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from osoji.config import Config  # noqa: E402
from osoji.evidence_builders import BuildContext  # noqa: E402
from osoji.findings import Finding  # noqa: E402
from osoji.junk_triage import build_junk_claims  # noqa: E402
from osoji.triage import Claim  # noqa: E402

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
    """

    workdir = Path(workdir)
    target = workdir / case.key.replace("/", "__")

    _copy_tree(case.snapshot_root / "source", target)
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
