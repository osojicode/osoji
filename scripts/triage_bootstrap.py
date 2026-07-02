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


async def run_sdk_exploration(
    entries: list[dict[str, Any]],
    *,
    model: str | None,
    max_turns: int,
    concurrency: int,
) -> tuple[list[Finding], dict[str, dict[str, Any]], int, int]:
    """Exploration via the Claude Agent SDK (osojicode/work#51 workaround).

    `claude -p` cannot round-trip custom tool calls, so the in-process
    Triage exploration loop has no transport on the claude-code provider.
    The Agent SDK wraps the same CLI (Max OAuth auth carries over) and
    dispatches MCP tool calls to in-process callbacks — ExplorationExecutor
    remains the single implementation of read_file/grep/list_dir semantics,
    so traces stay comparable with the native exploration loop.
    """

    from claude_agent_sdk import (  # noqa: PLC0415
        ClaudeAgentOptions,
        create_sdk_mcp_server,
        query,
        tool,
    )

    from osoji.llm.claude_code import ClaudeCodeProvider  # noqa: PLC0415
    from osoji.tools import (  # noqa: PLC0415
        GREP_TOOL,
        LIST_DIR_TOOL,
        READ_FILE_TOOL,
        SUBMIT_TRIAGE_VERDICT_TOOL,
    )
    from osoji.triage_exec import ExplorationExecutor  # noqa: PLC0415

    config = Config(root_path=REPO_ROOT)
    repo_executor = ExplorationExecutor(config)
    resolved_model = model or config.model_for("medium")
    neutral_cwd = ClaudeCodeProvider._neutral_cwd()
    sem = asyncio.Semaphore(concurrency)

    async def explore_one(entry: dict[str, Any]) -> tuple[Finding, dict[str, Any], int, int]:
        finding = replace(Finding.from_dict(entry["finding"]), evidence=[])

        # Fixture claims explore their snapshot as a self-contained mini-repo,
        # rooted at <fixture_root>/source/. Anything above that — notably
        # expected.json, the answer key — must be unreachable, or the baseline
        # verdicts are contaminated (observed in the first SDK smoke test).
        fixture_root = entry.get("fixture_root")
        if fixture_root:
            source_root = REPO_ROOT / fixture_root / "source"
            executor = ExplorationExecutor(Config(root_path=source_root))
            prefix = f"{fixture_root}/source/"
            if finding.path.startswith(prefix):
                finding = replace(finding, path=finding.path[len(prefix):])
        else:
            executor = repo_executor
        trace: dict[str, Any] = {"finding_id": finding.id, "calls": []}
        verdict: dict[str, Any] = {}

        def retrieval(defn: dict[str, Any]):
            @tool(defn["name"], defn["description"], defn["input_schema"])
            async def _t(tool_args: dict[str, Any], _name: str = defn["name"]):
                trace["calls"].append(
                    {"turn": len(trace["calls"]), "name": _name, "input": tool_args}
                )
                return {"content": [{"type": "text", "text": executor.run(_name, tool_args)}]}
            return _t

        @tool(
            SUBMIT_TRIAGE_VERDICT_TOOL["name"],
            SUBMIT_TRIAGE_VERDICT_TOOL["description"],
            SUBMIT_TRIAGE_VERDICT_TOOL["input_schema"],
        )
        async def submit(tool_args: dict[str, Any]):
            trace["calls"].append(
                {"turn": len(trace["calls"]), "name": "submit_triage_verdict", "input": tool_args}
            )
            verdict.update(tool_args)
            return {"content": [{"type": "text", "text": "Verdict recorded. You are done."}]}

        server = create_sdk_mcp_server(
            "explore",
            tools=[retrieval(READ_FILE_TOOL), retrieval(GREP_TOOL),
                   retrieval(LIST_DIR_TOOL), submit],
        )
        options = ClaudeAgentOptions(
            tools=[],  # no built-in tools: the repo is visible only through ours
            mcp_servers={"explore": server},
            allowed_tools=[
                "mcp__explore__read_file", "mcp__explore__grep",
                "mcp__explore__list_dir", "mcp__explore__submit_triage_verdict",
            ],
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            model=resolved_model,
            max_turns=max_turns,
            cwd=neutral_cwd,
        )
        prompt = (
            Triage._render_claim_block(0, finding)
            + "\nExplore the repository with read_file / grep / list_dir as needed, "
            "then call submit_triage_verdict with your decision."
        )
        in_tok = out_tok = 0
        cost_usd = 0.0
        async with sem:
            try:
                async for message in query(prompt=prompt, options=options):
                    usage = getattr(message, "usage", None)
                    if isinstance(usage, dict):
                        in_tok += usage.get("input_tokens", 0) or 0
                        out_tok += usage.get("output_tokens", 0) or 0
                    if type(message).__name__ == "ResultMessage":
                        cost_usd += getattr(message, "total_cost_usd", None) or 0.0
            except Exception as exc:  # noqa: BLE001 — one claim must not kill the batch
                # The SDK raises on the CLI's max-turns error result; a verdict
                # submitted on the final turn is still valid. Everything else is
                # recorded on the trace and yields 'uncertain' below.
                trace["error"] = str(exc)

        trace["cost_usd"] = round(cost_usd, 6)
        if verdict:
            decided = replace(
                finding,
                verdict=verdict.get("verdict"),
                confidence=verdict.get("confidence"),
                triage_reasoning=verdict.get("reasoning"),
                suggested_fix=verdict.get("suggested_fix"),
                severity=verdict.get("severity"),
            )
        else:
            decided = replace(
                finding,
                verdict="uncertain",
                confidence=0.0,
                triage_reasoning="Exploration did not produce a verdict within the turn limit.",
            )
        print(f"  [{entry['slug']}] verdict={decided.verdict} calls={len(trace['calls'])}")
        return decided, trace, in_tok, out_tok

    results = await asyncio.gather(*(explore_one(e) for e in entries))
    findings = [r[0] for r in results]
    traces_by_id = {r[1]["finding_id"]: r[1] for r in results}
    return findings, traces_by_id, sum(r[2] for r in results), sum(r[3] for r in results)


async def run(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    entries = manifest["entries"]
    if args.only:
        wanted = set(args.only)
        entries = [e for e in entries if e["slug"] in wanted]
    mode = args.mode

    if mode == "exploration-sdk":
        findings, traces_by_id, in_tokens, out_tokens = await run_sdk_exploration(
            entries, model=args.model, max_turns=args.max_turns,
            concurrency=args.concurrency,
        )
    else:
        claims = entries_to_claims(entries, strip_evidence=(mode == "exploration"))
        config = Config(root_path=REPO_ROOT, provider=args.provider, model=args.model)
        triage = Triage(config)
        result = await triage.decide_batch(
            claims, mode=mode, system_prompt=TRIAGE_SYSTEM_PROMPT
        )
        findings = result.findings
        traces_by_id = {t["finding_id"]: t for t in result.exploration_traces}
        in_tokens, out_tokens = result.input_tokens, result.output_tokens

    args.out.mkdir(parents=True, exist_ok=True)
    for entry, finding in zip(entries, findings):
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

    summary = summarize(entries, findings)
    summary["mode"] = mode
    summary["input_tokens"] = in_tokens
    summary["output_tokens"] = out_tokens

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
    print(f"tokens: in={in_tokens} out={out_tokens}")
    print(f"artifacts: {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, mode in (
        ("explore", "exploration"),
        ("explore-sdk", "exploration-sdk"),
        ("claim", "claim"),
    ):
        p = sub.add_parser(name)
        p.set_defaults(mode=mode)
        p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        p.add_argument("--out", type=Path, default=DEFAULT_TRACE_DIR)
        p.add_argument("--provider", default=None, help="LLM provider (e.g. claude-code)")
        p.add_argument("--model", default=None)
        p.add_argument("--baseline", type=Path, default=None,
                       help="explore-summary.json to measure verdict-disagreement against")
        p.add_argument("--only", nargs="*", default=None, help="restrict to these slugs")
        p.add_argument("--max-turns", type=int, default=16)
        p.add_argument("--concurrency", type=int, default=3,
                       help="parallel claims for explore-sdk")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
