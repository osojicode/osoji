"""Score Tier A against a comparator inventory (the honesty-test gate).

Usage:
    python scripts/tier_a_replay.py --repo <checkout> --inventory <rows.jsonl> \
        [--kinds nonexistent_artifact,wrong_path,wrong_command,stale_pointer]

Runs the zero-LLM Tier A layer on the checkout and reports, for every
inventory row of the selected kinds, whether a contradicted packet on the same
doc names the artifact the comparator corrected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from osoji.config import Config  # noqa: E402
from osoji.tier_a import EvidencePacket, run_tier_a  # noqa: E402

DEFAULT_KINDS = "nonexistent_artifact,wrong_path,wrong_command,stale_pointer"


def score_rows(rows: list[dict], packets: list[EvidencePacket]) -> list[dict]:
    by_doc: dict[str, list[EvidencePacket]] = {}
    for p in packets:
        if p.verdict == "contradicted":
            by_doc.setdefault(p.claim.doc_path.replace("\\", "/"), []).append(p)
    out = []
    for r in rows:
        claim_text = (r.get("claim") or "").lower()
        matched = next((p.claim.name for p in by_doc.get(r["path"].replace("\\", "/"), [])
                        if p.claim.name.lower() in claim_text), None)
        out.append({**r, "hit": matched is not None, "matched": matched})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--inventory", required=True, type=Path)
    ap.add_argument("--kinds", default=DEFAULT_KINDS)
    args = ap.parse_args()
    kinds = set(args.kinds.split(","))
    rows = [json.loads(l) for l in args.inventory.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("partition") in ("correction", "deletion")
            and r.get("domain") == "checkout" and r.get("kind") in kinds]
    packets = run_tier_a(Config(root_path=args.repo.resolve()))
    scored = score_rows(rows, packets)
    for r in scored:
        print(f"{'HIT ' if r['hit'] else 'miss'} {r['path']}:{r.get('old_start')} [{r['kind']}] {r.get('claim','')[:110]}")
    hits = sum(1 for r in scored if r["hit"])
    contradicted = sum(1 for p in packets if p.verdict == "contradicted")
    print(json.dumps({"rows": len(scored), "hits": hits, "recall": round(hits / len(scored), 3) if scored else None,
                      "contradicted_packets": contradicted, "claims_checked": len(packets)}))


if __name__ == "__main__":
    main()
