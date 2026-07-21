"""corpus-replay entrypoint emitting osoji-verdict/1 NDJSON.

Thin argparse shell over ``eval_lib.py`` — all behavior (case selection,
staging, claim building, the Triage decide loop, metrics, NDJSON framing)
lives there; this module only parses arguments, calls into the library, and
sets exit codes. Consumed standalone (a human replaying the corpus locally)
and by the proctor corpus-replay harness (osojicode/work#63).

Examples::

    python scripts/corpus_replay.py --gate-check
    python scripts/corpus_replay.py --variant baseline=@default \\
        --variant no_significance=@omit:significance --repeats 3 \\
        --out runs/eval-001.ndjson
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import eval_lib  # noqa: E402
from eval_lib import (  # noqa: E402
    CORPUS_ROOT,
    GateReport,
    check_gepa_gate,
    evaluate_corpus,
    load_splits,
    resolve_variant,
    select_cases,
    write_verdict_ndjson,
)
from osoji.config import Config  # noqa: E402

#: Default bootstrap manifest when --source includes "bootstrap" and
#: --bootstrap is not given (mirrors triage_bootstrap.py's own default).
DEFAULT_BOOTSTRAP_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "manifest.json"

SPLIT_CHOICES = ("train", "val", "holdout")


def _parse_only(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(key.strip() for key in raw.split(",") if key.strip())


def _parse_variants(specs: list[str] | None) -> list[eval_lib.Variant]:
    """Resolve every ``--variant`` spec, rejecting duplicate names.

    Defaults to a single ``baseline=@default`` variant when none are given.
    """

    variants: list[eval_lib.Variant] = []
    seen: set[str] = set()
    for spec in specs or ["baseline=@default"]:
        variant = resolve_variant(spec)
        if variant.name in seen:
            raise ValueError(f"duplicate --variant name: {variant.name!r}")
        seen.add(variant.name)
        variants.append(variant)
    return variants


def _print_gate_report(report: GateReport) -> None:
    status = "PASSED" if report.passed else "FAILED"
    print(f"GEPA gate: {status}")
    print(f"  non-gray cases: {report.nongray_count} (required: {report.required})")
    print(f"  splits.json non-empty: {report.splits_nonempty}")
    print(f"  split coverage ok: {report.coverage_ok}")
    if report.missing_from_splits:
        print(f"  missing from splits.json: {', '.join(report.missing_from_splits)}")
    if report.extra_in_splits:
        print(f"  stale assignments (no matching case): {', '.join(report.extra_in_splits)}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=CORPUS_ROOT, help="corpus-case/1 root directory"
    )
    parser.add_argument(
        "--bootstrap", type=Path, default=None, help="bootstrap manifest.json (see --source)"
    )
    parser.add_argument(
        "--source", choices=("corpus", "bootstrap", "both"), default="corpus",
        help="which case source(s) to replay",
    )
    parser.add_argument(
        "--variant", action="append", metavar="name=value", default=None,
        help="repeatable; e.g. baseline=@default. Defaults to baseline=@default.",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--repeat-offset", type=int, default=0)
    parser.add_argument("--run-id", default=None, help="default: eval-YYYYMMDD-<8hex>")
    parser.add_argument(
        "--split", choices=SPLIT_CHOICES, default=None, help="requires <corpus>/splits.json"
    )
    parser.add_argument("--only", default=None, metavar="key1,key2")
    parser.add_argument("--exclude-gray", action="store_true")
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default=None, help="override the resolved model")
    parser.add_argument("--out", default="-", help="NDJSON output path, or - for stdout")
    parser.add_argument(
        "--gate-check", action="store_true",
        help="print the GEPA gate report for the current selection and exit "
        "0/1 — no provider construction, no LLM calls",
    )
    return parser


def _load_splits_for(corpus_root: Path) -> dict:
    splits_path = corpus_root / "splits.json"
    return load_splits(splits_path)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    only = _parse_only(args.only)

    try:
        variants = _parse_variants(args.variant)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    splits: dict | None = None
    if args.split is not None:
        try:
            splits = _load_splits_for(args.corpus)
        except (OSError, ValueError) as exc:
            print(f"error: cannot load splits.json for --split {args.split!r}: {exc}",
                  file=sys.stderr)
            return 2
        if args.split not in splits.get("ratios", {}):
            print(
                f"error: unknown split {args.split!r} "
                f"(known: {sorted(splits.get('ratios', {}))})",
                file=sys.stderr,
            )
            return 2

    bootstrap_manifest = args.bootstrap
    if args.source in ("bootstrap", "both") and bootstrap_manifest is None:
        bootstrap_manifest = DEFAULT_BOOTSTRAP_MANIFEST

    try:
        cases = select_cases(
            source=args.source,
            corpus_root=args.corpus,
            bootstrap_manifest=bootstrap_manifest,
            split=args.split,
            splits=splits,
            only=only,
            exclude_gray=args.exclude_gray,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not cases:
        print("error: empty case selection", file=sys.stderr)
        return 2

    if args.gate_check:
        gate_splits = splits
        if gate_splits is None:
            try:
                gate_splits = _load_splits_for(args.corpus)
            except (OSError, ValueError) as exc:
                print(f"error: cannot load splits.json for --gate-check: {exc}", file=sys.stderr)
                return 2
        report = check_gepa_gate(cases, gate_splits)
        _print_gate_report(report)
        return 0 if report.passed else 1

    run_id = args.run_id or eval_lib.default_run_id()

    def _config_factory() -> Config:
        return Config(
            root_path=REPO_ROOT,
            provider=args.provider,
            model=args.model,
            respect_gitignore=False,
        )

    with tempfile.TemporaryDirectory(prefix="osoji-corpus-replay-") as tmp:
        run = asyncio.run(
            evaluate_corpus(
                cases,
                variants,
                repeats=args.repeats,
                repeat_offset=args.repeat_offset,
                run_id=run_id,
                config_factory=_config_factory,
                workdir=Path(tmp),
                corpus_root=args.corpus,
                split=args.split,
                only=only,
                exclude_gray=args.exclude_gray,
            )
        )

    out = sys.stdout if args.out == "-" else Path(args.out)
    write_verdict_ndjson(run.records, run.run_meta, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
