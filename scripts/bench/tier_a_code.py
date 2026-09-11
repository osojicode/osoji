"""Run Tier A on code claims over a checkout and write findings for ``bench.score``.

Usage:
    python scripts/bench/tier_a_code.py --repo <checkout> --parent <sha> --out <findings-dir>

Zero LLM. Writes ``<out>/<parent>.json`` with the contradicted packets as audit-shaped
issues (``exclude_key: "code-claims"``) and ``<out>/packets/<parent>.json`` with every
packet, all verdicts, for the precision review (wiki sources/0008: every contradicted
packet over the whole tree is hand-verified, not only those on benchmark rows).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from osoji.config import Config  # noqa: E402
from osoji.tier_a import EvidencePacket, packet_message, packet_remediation, run_tier_a_code  # noqa: E402


def issues_from_packets(packets: list[EvidencePacket]) -> list[dict]:
    issues: list[dict] = []
    for p in packets:
        if p.verdict != "contradicted":
            continue
        severity, confidence = p.grade or ("warning", 0.8)
        issues.append({
            "path": p.claim.doc_path, "severity": severity, "confidence": confidence,
            "category": f"code_{p.claim.kind}", "message": packet_message(p),
            "remediation": packet_remediation(p), "line_start": p.claim.line, "line_end": p.claim.line,
            "exclude_key": "code-claims", "verdict": "confirmed",
            "origin": {"source": "static", "plugin": "tier_a_code"},
        })
    return issues


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--parent", required=True, help="commit sha the checkout is at (findings file name)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-gitignore", action="store_true")
    args = ap.parse_args()

    started = time.monotonic()
    config = Config(root_path=args.repo.resolve(), respect_gitignore=not args.no_gitignore, quiet=True)
    packets = run_tier_a_code(config)
    elapsed = time.monotonic() - started

    issues = issues_from_packets(packets)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.parent}.json").write_text(json.dumps({
        "issues": issues,
        "run_meta": {"parent": args.parent, "kind": "tier-a-code", "seconds": round(elapsed, 1),
                     "claims_checked": len(packets), "contradicted": len(issues)},
    }, indent=1), encoding="utf-8")
    (args.out / "packets").mkdir(exist_ok=True)
    (args.out / "packets" / f"{args.parent}.json").write_text(
        json.dumps([p.to_dict() for p in packets], indent=1, ensure_ascii=False), encoding="utf-8")

    by_kind = collections.Counter((p.claim.kind, p.verdict) for p in packets)
    kinds = sorted({k for k, _ in by_kind})
    table = {k: {v: by_kind.get((k, v), 0) for v in ("contradicted", "supported", "undecidable")} for k in kinds}
    print(json.dumps({"parent": args.parent, "seconds": round(elapsed, 1), "claims_checked": len(packets),
                      "contradicted": len(issues), "by_kind": table}, indent=1))


if __name__ == "__main__":
    main()
