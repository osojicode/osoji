"""Run osoji at docs-fix parents over the touched docs (wiki specs/0005, Phase 0).

For each parent commit in the plan the runner checks the working tree out
at that commit, refreshes osoji's substrate there (shadow docs are cached
by source hash, so consecutive parents share most of the work), analyses
only the documents the fix touched, and writes ``<parent>.json`` with the
issues in the audit's shape for ``bench.score``. The tree is restored to
its original ref afterwards. Parents already written are skipped, so a run
is resumable; failures are recorded per parent and never stop the batch.

Usage:
    python scripts/bench/run.py --repo <checkout> --rows bench/<name>/rows.labeled.jsonl \
        --out bench/<name>/runs/<run-id> [--reader r1] [--max-parents N] [--skip-shadow] [--dry-run]

``--repo`` must be a working tree (e.g. a worktree of the partial clone:
``git -C ~/projects/bench-repos/<name> worktree add ~/projects/bench-work/<name> <sha>``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # run as `python scripts/bench/run.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.score import counting_rows, norm_path  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()


def select_parents(rows: list[dict], *, reader: str | None, max_parents: int | None) -> list[dict]:
    """Counting rows grouped by parent commit, newest first."""

    by_parent: dict[str, dict] = {}
    for row in counting_rows(rows, reader):
        entry = by_parent.setdefault(row["parent"], {
            "parent": row["parent"], "date": row.get("commit_date", ""), "docs": [], "rows": 0,
        })
        entry["rows"] += 1
        path = norm_path(row["path"])
        if path not in entry["docs"]:
            entry["docs"].append(path)
    plan = sorted(by_parent.values(), key=lambda e: e["date"], reverse=True)
    return plan[:max_parents] if max_parents else plan


def issues_from_results(results) -> list[dict]:
    """DocAnalysisResults → issue dicts in the shape ``run_audit_async`` emits."""

    issues: list[dict] = []
    for item in results:
        path = norm_path(str(item.path))
        if item.is_debris:
            issues.append({
                "path": path, "severity": "error", "category": "debris",
                "message": f"Documentation debris: {item.classification_reason}",
                "remediation": "Delete this file", "line_start": None, "line_end": None,
                "origin": {"source": "llm", "plugin": "doc_analysis"}, "exclude_key": "doc-analysis",
            })
            continue
        for f in item.findings:
            tag = f" [evidence: {f.shadow_ref} — \"{f.evidence}\"]" if f.shadow_ref and f.evidence else ""
            issues.append({
                "path": path, "severity": f.severity, "category": f"doc_{f.category}",
                "message": f"{f.description}{tag}", "remediation": f.remediation,
                "line_start": None, "line_end": None,
                "origin": {"source": "llm", "plugin": "doc_analysis"}, "exclude_key": "doc-analysis",
                "finding_id": f.finding_id, "verdict": f.verdict, "confidence": f.confidence,
                "triage_reasoning": f.triage_reasoning, "suggested_fix": f.suggested_fix,
                "description_class": f.description_class,
            })
    return issues


def run_parents(
    repo: Path, plan: list[dict], out_dir: Path, *,
    shadow: Callable[[Path], dict], analyze: Callable[[Path, list[str]], list],
) -> dict:
    """Execute the plan; one JSON per parent under ``out_dir``. Restores the checkout."""

    out_dir.mkdir(parents=True, exist_ok=True)
    original = _git(repo, "symbolic-ref", "-q", "--short", "HEAD") if _is_on_branch(repo) else _git(repo, "rev-parse", "HEAD")
    counts = {"parents_run": 0, "parents_skipped": 0, "parents_failed": 0}
    try:
        for entry in plan:
            parent = entry["parent"]
            out_file = out_dir / f"{parent}.json"
            if out_file.exists():
                counts["parents_skipped"] += 1
                continue
            started = time.monotonic()
            run_at = datetime.now(timezone.utc).isoformat()
            try:
                _git(repo, "checkout", "-q", parent)
                shadow_meta = shadow(repo)
                results = analyze(repo, list(entry["docs"]))
                issues = issues_from_results(results)
                out_file.write_text(json.dumps({
                    "issues": issues,
                    "meta": {
                        "parent": parent, "docs": list(entry["docs"]), "rows": entry.get("rows"),
                        "shadow": shadow_meta, "seconds": round(time.monotonic() - started, 1),
                        "run_at": run_at, "issues": len(issues),
                    },
                }, indent=1, ensure_ascii=False), encoding="utf-8")
                counts["parents_run"] += 1
                print(f"  [{parent[:10]}] {len(entry['docs'])} doc(s), {len(issues)} issue(s), "
                      f"{time.monotonic() - started:.0f}s", flush=True)
            except Exception:
                counts["parents_failed"] += 1
                (out_dir / f"{parent}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                print(f"  [{parent[:10]}] FAILED (see {parent}.error.txt)", flush=True)
    finally:
        _git(repo, "checkout", "-q", original)
    return counts


def _is_on_branch(repo: Path) -> bool:
    return subprocess.run(["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                          capture_output=True).returncode == 0


# ── default steps: the shipping pipeline ─────────────────────────────────────


def default_shadow(workdir: Path) -> dict:
    """Refresh shadow docs in ``workdir`` (cached by source hash across parents)."""

    from osoji.config import Config
    from osoji.shadow import generate_shadow_docs

    started = time.monotonic()
    ok = generate_shadow_docs(Config(root_path=workdir, quiet=True))
    return {"ok": ok, "seconds": round(time.monotonic() - started, 1)}


def default_analyze(workdir: Path, docs: list[str]) -> list:
    """Run the shipping doc checker over ``docs`` only."""

    from unittest.mock import patch

    from osoji import doc_analysis
    from osoji.config import Config
    from osoji.llm.runtime import create_runtime

    config = Config(root_path=workdir, quiet=True)
    targets = [workdir / d for d in docs if (workdir / d).is_file()]

    async def go():
        provider, _ = create_runtime(config)
        try:
            with patch.object(doc_analysis, "find_doc_candidates", return_value=targets):
                return await doc_analysis.analyze_docs_async(provider, config)
        finally:
            await provider.close()

    return asyncio.run(go())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path, help="working tree to check out parents in")
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--reader", default=None)
    ap.add_argument("--max-parents", type=int, default=None)
    ap.add_argument("--skip-shadow", action="store_true", help="do not refresh shadow docs (cells that don't use them)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    ap.add_argument("--env-root", type=Path, default=Path("."), help="where .env lives (API keys)")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(args.env_root.resolve() / ".env")
    os.environ.setdefault("PYTHONUTF8", "1")

    rows = [json.loads(l) for l in args.rows.read_text(encoding="utf-8").splitlines() if l.strip()]
    plan = select_parents(rows, reader=args.reader, max_parents=args.max_parents)
    print(json.dumps({"parents": len(plan), "docs": sum(len(p["docs"]) for p in plan),
                      "rows": sum(p["rows"] for p in plan)}, indent=2))
    if args.dry_run:
        for p in plan:
            print(f"  {p['parent'][:10]} {p['date'][:10]} rows={p['rows']} docs={p['docs']}")
        return
    shadow = (lambda w: {"skipped": True}) if args.skip_shadow else default_shadow
    counts = run_parents(args.repo.resolve(), plan, args.out, shadow=shadow, analyze=default_analyze)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
