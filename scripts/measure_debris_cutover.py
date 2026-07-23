"""Measure the V1-4 debris cutover delta (osojicode/work#27, Phase E).

Compares claim-set construction over the live ``.osoji/findings/`` debris
corpus between the V1-3 inline Claim Builder rule (cross-file FactsDB refs OR
latent-bug type definitions — replicated verbatim below) and the V1-4
mechanized builders (``build_debris_claims`` on the generalized schema). No
LLM calls; nothing is triaged. The output is the escalation-rate baseline the
ticket's falsifiability metrics require.

Usage:

    PYTHONUTF8=1 python scripts/measure_debris_cutover.py \
        [--out tests/fixtures/bootstrap/debris-cutover.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from osoji.claim_builder import build_debris_claims  # noqa: E402
from osoji.config import Config  # noqa: E402
from osoji.evidence_builders import (  # noqa: E402
    _extract_all_symbols_from_debris,
    _infer_variable_type,
    _lookup_type_definitions,
)


def load_debris_ignoring_impl_hash(config: Config) -> list[dict]:
    """audit._load_raw_debris minus the ``is_findings_current`` gate.

    This branch changes osoji source, so ``impl_hash`` drifts and the live
    findings sidecars (generated 2026-07-01, pre-branch) would all be filtered
    as stale. For *measurement* the gate is irrelevant — both the legacy rule
    and the mechanized builders see identical inputs — so it is deliberately
    bypassed here. Production keeps the gate.
    """

    raw_debris: list[dict] = []
    findings_dir = config.root_path / ".osoji" / "findings"
    if not findings_dir.exists():
        return raw_debris
    for findings_file in sorted(findings_dir.rglob("*.findings.json")):
        try:
            data = json.loads(findings_file.read_text(encoding="utf-8"))
            source_path_str = data["source"]
            if not (config.root_path / source_path_str).exists():
                continue
            for finding in data.get("findings", []):
                raw_debris.append(
                    {"source": source_path_str, "source_path": Path(source_path_str), **finding}
                )
        except (json.JSONDecodeError, KeyError):
            continue
    return raw_debris


def legacy_is_eligible(finding: dict) -> bool:
    """The V1-3 eligibility gate, replicated verbatim (retired from production
    by osoji#168 — this script measures against the frozen legacy behavior)."""

    category = finding.get("category", "")
    if category in ("dead_code", "latent_bug"):
        return True
    if category == "stale_comment" and finding.get("cross_file_verification_needed"):
        return True
    return False


def legacy_claim_exists(config: Config, finding: dict, facts_db, symbols_by_file) -> bool:
    """The V1-3 inline sufficiency rule, replicated verbatim from the
    pre-cutover ``_try_build_claim`` (commit 9199a37^)."""

    desc = finding.get("description", "")
    source = finding.get("source") or finding.get("source_path") or ""
    if not source:
        return False
    source = str(source)
    symbols = _extract_all_symbols_from_debris(desc)
    if not symbols:
        return False
    best_refs: list[dict] = []
    for sym in symbols:
        refs = facts_db.cross_file_references(sym, source)
        if len(refs) > len(best_refs):
            best_refs = refs
    type_defs: list[dict] = []
    if finding.get("category") == "latent_bug":
        type_names = [s for s in symbols if s and s[0].isupper() and not s.isupper()]
        type_names.extend(
            _infer_variable_type(config, source, finding.get("line_start"), desc)
        )
        if type_names:
            type_defs = _lookup_type_definitions(config, type_names, symbols_by_file)
    return bool(best_refs or type_defs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path,
        default=REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "debris-cutover.json",
    )
    args = parser.parse_args()

    from osoji.facts import FactsDB
    from osoji.symbols import load_all_symbols

    config = Config(root_path=REPO_ROOT)
    raw_debris = load_debris_ignoring_impl_hash(config)
    eligible = [f for f in raw_debris if legacy_is_eligible(f)]

    facts_db = FactsDB(config)
    symbols_by_file = load_all_symbols(config)

    old_claims = sum(
        1 for f in eligible if legacy_claim_exists(config, f, facts_db, symbols_by_file)
    )
    old_escalate = len(eligible) - old_claims

    claims, _, new_escalate = build_debris_claims(
        config, raw_debris, facts_db=facts_db, symbols_by_file=symbols_by_file
    )

    report = {
        "debris_total": len(raw_debris),
        "eligible": len(eligible),
        "old": {
            "claims": old_claims,
            "would_escalate": old_escalate,
            "escalation_rate": old_escalate / len(eligible) if eligible else 0.0,
        },
        "new": {
            "claims": len(claims),
            "would_escalate": new_escalate,
            "escalation_rate": new_escalate / len(eligible) if eligible else 0.0,
        },
    }
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
