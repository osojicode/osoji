"""V1-4 Claim Builder bootstrap harness (osojicode/work#27).

Runs the unified Triage stage over the curated bootstrap set in either mode:

- ``explore``: exploration-mode baseline. Each claim is presented with its
  Evidence STRIPPED so the LLM must retrieve everything itself via
  read_file / grep / list_dir — the tool-call traces are the observation
  data the Claim Builder schema is mined from (see osojicode/wiki
  ``concepts/self-sufficient-claims.md``, *Bootstrap path*).
- ``claim``: claim-mode ablation run. Each claim keeps the Evidence the
  Claim Builder assembled; verdicts are compared against the exploration
  baseline to measure verdict-disagreement (ship gate: < 5%, spec 0001
  verification criterion 5).

The bootstrap set lives in ``tests/fixtures/bootstrap/manifest.json``:

    {
      "commit": "<git sha the sampled findings were audited at>",
      "entries": [
        {
          "slug": "debris-dead-code-001",
          "origin": "audit" | "fixture",
          "category": "<native detector category>",
          "adjudicated_verdict": "confirmed" | "dismissed",
          "adjudication_notes": "...",
          "finding": { <Finding.to_dict() shape> }
        },
        ...
      ]
    }

Usage:

    python scripts/triage_bootstrap.py explore --provider claude-code
    python scripts/triage_bootstrap.py claim --provider claude-code \
        --baseline tests/fixtures/bootstrap/traces/explore-summary.json

Outputs land under ``tests/fixtures/bootstrap/traces/`` (committed as
reproducibility artifacts per ticket #27): one ``<slug>.json`` per claim
(verdict + trace + tokens) and a run summary with per-category agreement
against the adjudicated labels.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from osoji.config import Config  # noqa: E402
from osoji.findings import Finding  # noqa: E402
from osoji.triage import TRIAGE_SYSTEM_PROMPT, Claim, Triage  # noqa: E402

BOOTSTRAP_DIR = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
DEFAULT_MANIFEST = BOOTSTRAP_DIR / "manifest.json"
DEFAULT_TRACE_DIR = BOOTSTRAP_DIR / "traces"


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["entries"]:
        for key in ("slug", "category", "adjudicated_verdict", "finding"):
            if key not in entry:
                raise ValueError(f"manifest entry missing {key!r}: {entry.get('slug', entry)}")
    return data


def entries_to_claims(entries: list[dict[str, Any]], *, strip_evidence: bool) -> list[Claim]:
    claims = []
    for entry in entries:
        finding = Finding.from_dict(entry["finding"])
        if strip_evidence:
            # Exploration baseline must not see pre-assembled evidence, or the
            # mined traces would only reflect what we already chose to gather.
            finding = replace(finding, evidence=[])
        claims.append(Claim(finding=finding))
    return claims


def summarize(
    entries: list[dict[str, Any]], findings: list[Finding]
) -> dict[str, Any]:
    per_category: dict[str, dict[str, int]] = {}
    rows = []
    for entry, finding in zip(entries, findings):
        cat = entry["category"]
        agree = finding.verdict == entry["adjudicated_verdict"]
        stats = per_category.setdefault(cat, {"n": 0, "agree": 0, "uncertain": 0})
        stats["n"] += 1
        stats["agree"] += int(agree)
        stats["uncertain"] += int(finding.verdict == "uncertain")
        rows.append(
            {
                "slug": entry["slug"],
                "category": cat,
                "adjudicated": entry["adjudicated_verdict"],
                "verdict": finding.verdict,
                "confidence": finding.confidence,
                "agree": agree,
            }
        )
    total = len(rows)
    agree_total = sum(1 for r in rows if r["agree"])
    return {
        "n": total,
        "accuracy": agree_total / total if total else 0.0,
        "per_category": per_category,
        "rows": rows,
    }


async def run(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    entries = manifest["entries"]
    if args.only:
        wanted = set(args.only)
        entries = [e for e in entries if e["slug"] in wanted]
    mode = args.mode
    claims = entries_to_claims(entries, strip_evidence=(mode == "exploration"))

    config = Config(root_path=REPO_ROOT, provider=args.provider, model=args.model)
    triage = Triage(config)
    result = await triage.decide_batch(
        claims, mode=mode, system_prompt=TRIAGE_SYSTEM_PROMPT
    )

    args.out.mkdir(parents=True, exist_ok=True)
    traces_by_id = {t["finding_id"]: t for t in result.exploration_traces}
    for entry, finding in zip(entries, result.findings):
        record = {
            "slug": entry["slug"],
            "mode": mode,
            "adjudicated_verdict": entry["adjudicated_verdict"],
            "finding": finding.to_dict(),
            "trace": traces_by_id.get(finding.id),
        }
        out_path = args.out / f"{mode}-{entry['slug']}.json"
        out_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )

    summary = summarize(entries, result.findings)
    summary["mode"] = mode
    summary["input_tokens"] = result.input_tokens
    summary["output_tokens"] = result.output_tokens

    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        base_verdicts = {r["slug"]: r["verdict"] for r in baseline["rows"]}
        disagreements = [
            {"slug": r["slug"], "baseline": base_verdicts.get(r["slug"]), "now": r["verdict"]}
            for r in summary["rows"]
            if r["slug"] in base_verdicts and base_verdicts[r["slug"]] != r["verdict"]
        ]
        summary["baseline_disagreement_rate"] = (
            len(disagreements) / len(summary["rows"]) if summary["rows"] else 0.0
        )
        summary["baseline_disagreements"] = disagreements

    summary_path = args.out / f"{mode}-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"mode={mode} n={summary['n']} accuracy={summary['accuracy']:.2%}")
    for cat, stats in sorted(summary["per_category"].items()):
        print(f"  {cat}: {stats['agree']}/{stats['n']} agree, {stats['uncertain']} uncertain")
    if "baseline_disagreement_rate" in summary:
        print(f"  disagreement vs baseline: {summary['baseline_disagreement_rate']:.2%}")
    print(f"tokens: in={result.input_tokens} out={result.output_tokens}")
    print(f"artifacts: {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, mode in (("explore", "exploration"), ("claim", "claim")):
        p = sub.add_parser(name)
        p.set_defaults(mode=mode)
        p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        p.add_argument("--out", type=Path, default=DEFAULT_TRACE_DIR)
        p.add_argument("--provider", default=None, help="LLM provider (e.g. claude-code)")
        p.add_argument("--model", default=None)
        p.add_argument("--baseline", type=Path, default=None,
                       help="explore-summary.json to measure verdict-disagreement against")
        p.add_argument("--only", nargs="*", default=None, help="restrict to these slugs")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
