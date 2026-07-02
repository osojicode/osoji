"""V1-4 Phase C trace mining (osojicode/work#27).

Mines the *correct* exploration traces from the Phase B baseline run for the
Evidence kinds the LLM consistently consulted per finding category. The output
is the requirements doc for mechanizing the Claim Builder (see osojicode/wiki
``concepts/self-sufficient-claims.md``, *Bootstrap path*, step 2): a per-category
report of what was grep'd (pattern shape, breadth), what was read (scope), and a
machine-drafted evidence-kind proposal that a human ratifies before any builder
code is written.

Only ``agree: true`` rows of the baseline summary are mined — the LLM sometimes
wanders into hallucinated paths and we don't want to mechanize bad exploration.

Traces record tool-call *inputs* only. To classify a read as landing on a
referencing site, prior greps in the same trace are re-executed offline through
``ExplorationExecutor`` (read-only, root-confined) against the same roots the
exploration used. Fixture claims re-root at ``<fixture_root>/source/`` exactly
as ``triage_bootstrap.run_sdk_exploration`` did; audit claims re-execute against
the current working tree, so minor drift since the baseline commit is possible
(flagged in the report, tolerable for classification).

Usage:

    PYTHONUTF8=1 python scripts/mine_traces.py \
        [--traces-dir tests/fixtures/bootstrap/traces] \
        [--summary tests/fixtures/bootstrap/traces/exploration-sdk-summary.json] \
        [--manifest tests/fixtures/bootstrap/manifest.json] \
        [--out tests/fixtures/bootstrap/mining]

Outputs (committed as reproducibility artifacts per ticket #27):

- ``mining-report.json`` — per-category distributions + per-trace classified calls
- ``mining-report.md``   — human-readable tables, the cross-check against the
  manifest's ``evidence_consulted`` adjudication notes, and the DRAFT
  evidence-kind proposal for Checkpoint-1 ratification
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from osoji.config import Config  # noqa: E402
from osoji.triage_exec import ExplorationExecutor  # noqa: E402

BOOTSTRAP_DIR = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
DEFAULT_TRACES = BOOTSTRAP_DIR / "traces"
DEFAULT_SUMMARY = DEFAULT_TRACES / "exploration-sdk-summary.json"
DEFAULT_MANIFEST = BOOTSTRAP_DIR / "manifest.json"
DEFAULT_OUT = BOOTSTRAP_DIR / "mining"

TRACE_PREFIX = "exploration-sdk-"  # a stray legacy trace exists; filter on this

# Classification taxonomies. Closed sets, each with an `other` outlet — the
# other-rate is itself a signal the taxonomy is missing a class (CLAUDE.md,
# closed-set discipline).
GREP_SHAPES = ("import_probe", "symbol", "literal", "regex", "other")
GREP_BREADTHS = ("repo_wide", "scoped")
READ_SCOPES = (
    "flagged_region",
    "same_file_other",
    "shadow_doc",
    "referencing_site",
    "doc_file",
    "other_file",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMPORT_RE = re.compile(r"\b(import|from)\b")
_DOC_SUFFIXES = {".md", ".rst", ".txt"}
_REGION_TOLERANCE = 15  # lines of slack around the flagged region / a grep hit
_GREP_HIT_RE = re.compile(r"^(.+?):(\d+): ")


def _quoted_strings(*texts: str) -> set[str]:
    """String literals quoted in the claim prose ('x', "x", or `x`)."""

    found: set[str] = set()
    for text in texts:
        for match in re.finditer(r"[`'\"]([^`'\"\n]{1,80})[`'\"]", text or ""):
            found.add(match.group(1))
    return found


def _strip_boundaries(pattern: str) -> str:
    out = pattern
    for anchor in (r"\b", "^", "$"):
        out = out.replace(anchor, "")
    return out


def classify_grep(pattern: str, needles: set[str]) -> str:
    """Classify a grep pattern's shape.

    Shape describes the *kind* of probe, not whether it targeted the flagged
    symbol: a bare identifier the model invented is still a ``symbol`` probe.
    """

    stripped = _strip_boundaries(pattern)
    if _IMPORT_RE.search(stripped):
        return "import_probe"
    if _IDENTIFIER_RE.match(stripped):
        return "symbol"
    # A pattern that is (an escaping of) a string quoted in the claim prose is
    # a literal probe even when it contains regex metacharacters.
    for needle in needles:
        if stripped in (needle, re.escape(needle)):
            return "literal"
    unescaped = re.sub(r"\\.", "", stripped)
    if re.search(r"[.*+?()\[\]{}|]", unescaped):
        return "regex"
    if stripped:
        return "literal"
    return "other"


def parse_grep_hits(output: str) -> dict[str, set[int]]:
    """Parse ``path:line: text`` rows from an ExplorationExecutor grep result."""

    hits: dict[str, set[int]] = {}
    if output.startswith(("Error:", "No matches")):
        return hits
    for line in output.splitlines():
        match = _GREP_HIT_RE.match(line)
        if match:
            hits.setdefault(match.group(1), set()).add(int(match.group(2)))
    return hits


def _ranges_overlap(
    lo: int, hi: int, target_lo: int | None, target_hi: int | None
) -> bool:
    if target_lo is None and target_hi is None:
        return True
    t_lo = (target_lo or target_hi or 1) - _REGION_TOLERANCE
    t_hi = (target_hi or target_lo or 1) + _REGION_TOLERANCE
    return lo <= t_hi and hi >= t_lo


def classify_read(
    call_input: dict[str, Any],
    finding: dict[str, Any],
    grep_hits: dict[str, set[int]],
) -> str:
    path = str(call_input.get("path", "")).replace("\\", "/")
    start = call_input.get("start")
    end = call_input.get("end")
    lo = int(start) if start is not None else 1
    hi = int(end) if end is not None else 10**9

    if path == str(finding.get("path", "")).replace("\\", "/"):
        if _ranges_overlap(lo, hi, finding.get("line_start"), finding.get("line_end")):
            return "flagged_region"
        return "same_file_other"
    if ".osoji/shadow" in path:
        return "shadow_doc"
    hit_lines = grep_hits.get(path)
    if hit_lines and (
        start is None
        or any(lo - _REGION_TOLERANCE <= line <= hi + _REGION_TOLERANCE for line in hit_lines)
    ):
        return "referencing_site"
    if Path(path).suffix.lower() in _DOC_SUFFIXES:
        return "doc_file"
    return "other_file"


def executor_for(entry: dict[str, Any]) -> ExplorationExecutor:
    fixture_root = entry.get("fixture_root")
    if fixture_root:
        return ExplorationExecutor(Config(root_path=REPO_ROOT / fixture_root / "source"))
    return ExplorationExecutor(Config(root_path=REPO_ROOT))


def mine_trace(entry: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Classify every call of one trace; re-executes greps for read context."""

    finding = record["finding"]
    needles = _quoted_strings(
        finding.get("contract_claim", ""), finding.get("observed_behavior", "")
    )
    executor = executor_for(entry)

    grep_hits: dict[str, set[int]] = {}  # accumulated across PRIOR greps only
    classified: list[dict[str, Any]] = []
    for call in record["trace"]["calls"]:
        name, tool_input = call["name"], call.get("input", {})
        row: dict[str, Any] = {"turn": call["turn"], "name": name}
        if name == "grep":
            pattern = str(tool_input.get("pattern", ""))
            row["pattern"] = pattern
            row["shape"] = classify_grep(pattern, needles)
            row["breadth"] = "scoped" if tool_input.get("glob") else "repo_wide"
            if row["breadth"] == "scoped":
                row["glob"] = tool_input.get("glob")
            for path, lines in parse_grep_hits(
                executor.run("grep", tool_input)
            ).items():
                grep_hits.setdefault(path, set()).update(lines)
        elif name == "read_file":
            row["path"] = tool_input.get("path")
            row["scope"] = classify_read(tool_input, finding, grep_hits)
        elif name == "list_dir":
            row["path"] = tool_input.get("path", ".")
        elif name == "submit_triage_verdict":
            continue
        else:
            row["input"] = tool_input
        classified.append(row)

    return {
        "slug": record["slug"],
        "category": entry["category"],
        "origin": entry["origin"],
        "n_calls": len(classified),
        "calls": classified,
    }


def aggregate(mined: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-category distributions over the classified traces."""

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({m["category"] for m in mined}):
        traces = [m for m in mined if m["category"] == category]
        greps = Counter()
        reads = Counter()
        grep_presence = Counter()  # traces with >=1 grep of shape
        read_presence = Counter()  # traces with >=1 read of scope
        breadth_presence = Counter()
        first_actions = Counter()
        list_dir_calls = 0
        for trace in traces:
            calls = trace["calls"]
            if calls:
                first = calls[0]
                first_actions[
                    f"{first['name']}:{first.get('shape') or first.get('scope') or ''}".rstrip(":")
                ] += 1
            shapes_seen, scopes_seen, breadths_seen = set(), set(), set()
            for call in calls:
                if call["name"] == "grep":
                    greps[call["shape"]] += 1
                    shapes_seen.add(call["shape"])
                    breadths_seen.add(call["breadth"])
                elif call["name"] == "read_file":
                    reads[call["scope"]] += 1
                    scopes_seen.add(call["scope"])
                elif call["name"] == "list_dir":
                    list_dir_calls += 1
            for shape in shapes_seen:
                grep_presence[shape] += 1
            for scope in scopes_seen:
                read_presence[scope] += 1
            for breadth in breadths_seen:
                breadth_presence[breadth] += 1
        n = len(traces)
        call_counts = [t["n_calls"] for t in traces]
        by_category[category] = {
            "n_traces": n,
            "calls_mean": round(statistics.mean(call_counts), 1) if call_counts else 0,
            "calls_median": statistics.median(call_counts) if call_counts else 0,
            "calls_max": max(call_counts, default=0),
            "grep_calls_by_shape": dict(greps),
            "read_calls_by_scope": dict(reads),
            "list_dir_calls": list_dir_calls,
            "trace_pct_with_grep_shape": {
                shape: round(grep_presence[shape] / n, 2) for shape in GREP_SHAPES if grep_presence[shape]
            },
            "trace_pct_with_read_scope": {
                scope: round(read_presence[scope] / n, 2) for scope in READ_SCOPES if read_presence[scope]
            },
            "trace_pct_with_breadth": {
                b: round(breadth_presence[b] / n, 2) for b in GREP_BREADTHS if breadth_presence[b]
            },
            "first_action_histogram": dict(first_actions.most_common()),
        }
    return by_category


# Observation-class → candidate EvidenceKind mapping used by the DRAFT
# proposal. referencing-site reads fold into cross_file_reference because the
# mechanized kind carries context lines at each referencing site — the read is
# what the LLM did to *get* that context. type_signature consultation is not
# mechanically detectable from inputs alone (it looks like other_file reads);
# latent_bug's other_file reads are called out for human review instead.
_KIND_SOURCES: dict[str, dict[str, tuple[str, ...]]] = {
    "cross_file_reference": {
        "grep": ("symbol", "literal", "import_probe", "regex"),
        "read": ("referencing_site",),
    },
    "surrounding_code": {"read": ("flagged_region", "same_file_other")},
    "declared_intent": {"read": ("doc_file",)},
    "shadow_doc_claim": {"read": ("shadow_doc",)},
}
_REQUIRED_THRESHOLD = 0.70
_OPTIONAL_THRESHOLD = 0.30


def draft_proposal(by_category: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Machine-drafted evidence-kind proposal (human ratifies at Checkpoint 1)."""

    proposal: dict[str, Any] = {}
    for category, stats in by_category.items():
        n = stats["n_traces"]
        kinds: dict[str, Any] = {}
        for kind, sources in _KIND_SOURCES.items():
            # A trace supports the kind if it contains >=1 call of ANY mapped
            # class; presence percentages are per-class, so take the max as a
            # lower bound (a trace usually greps AND reads referencing sites).
            rates = [
                stats["trace_pct_with_grep_shape"].get(shape, 0.0)
                for shape in sources.get("grep", ())
            ] + [
                stats["trace_pct_with_read_scope"].get(scope, 0.0)
                for scope in sources.get("read", ())
            ]
            rate = max(rates, default=0.0)
            if rate >= _REQUIRED_THRESHOLD:
                kinds[kind] = {"tier": "required", "consult_rate_lower_bound": rate}
            elif rate >= _OPTIONAL_THRESHOLD:
                kinds[kind] = {"tier": "optional", "consult_rate_lower_bound": rate}
        proposal[category] = {"n_traces": n, "kinds": kinds}
    return proposal


_CONSULTED_KEYWORDS = {
    "grep": "grep",
    "read": "read_file",
    "found": "grep",
    "traced": "grep",
    "checked": "read_file",
}


def cross_check(
    mined_by_slug: dict[str, dict[str, Any]], entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compare adjudication ``evidence_consulted`` phrases with observed calls.

    Keyword heuristics only; mismatches are listed for human review, never
    auto-resolved.
    """

    mismatches = []
    for entry in entries:
        consulted = entry.get("evidence_consulted") or []
        mined = mined_by_slug.get(entry["slug"])
        if not consulted or mined is None:
            continue
        observed_tools = {c["name"] for c in mined["calls"]}
        for phrase in consulted:
            expected = {
                tool
                for keyword, tool in _CONSULTED_KEYWORDS.items()
                if keyword in phrase.lower()
            }
            if expected and not (expected & observed_tools):
                mismatches.append(
                    {
                        "slug": entry["slug"],
                        "phrase": phrase,
                        "expected_any_of": sorted(expected),
                        "observed_tools": sorted(observed_tools),
                    }
                )
    return mismatches


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# V1-4 trace-mining report (Phase C, osojicode/work#27)",
        "",
        f"Mined **{report['n_mined']}** correct traces "
        f"(`agree: true` rows of `{report['summary_file']}`); "
        f"excluded {len(report['excluded'])}: "
        + ", ".join(f"`{e['slug']}` ({e['reason']})" for e in report["excluded"]),
        "",
        "Audit-entry greps re-executed against the current working tree — minor "
        "drift vs the baseline commit is possible and tolerable for classification.",
        "",
        "## Per-category observations",
        "",
    ]
    for category, stats in report["by_category"].items():
        lines.append(f"### {category} ({stats['n_traces']} traces)")
        lines.append("")
        lines.append(
            f"- calls/trace: mean {stats['calls_mean']}, median {stats['calls_median']}, "
            f"max {stats['calls_max']}; list_dir calls: {stats['list_dir_calls']}"
        )
        lines.append(
            "- % traces with grep shape: "
            + (
                ", ".join(
                    f"{shape} **{pct:.0%}**"
                    for shape, pct in stats["trace_pct_with_grep_shape"].items()
                )
                or "none"
            )
        )
        lines.append(
            "- % traces with grep breadth: "
            + (
                ", ".join(
                    f"{b} **{pct:.0%}**" for b, pct in stats["trace_pct_with_breadth"].items()
                )
                or "none"
            )
        )
        lines.append(
            "- % traces with read scope: "
            + (
                ", ".join(
                    f"{scope} **{pct:.0%}**"
                    for scope, pct in stats["trace_pct_with_read_scope"].items()
                )
                or "none"
            )
        )
        lines.append(
            "- first action: "
            + ", ".join(f"{k} ×{v}" for k, v in stats["first_action_histogram"].items())
        )
        lines.append("")

    lines += [
        "## Cross-check vs adjudication `evidence_consulted`",
        "",
    ]
    if report["cross_check_mismatches"]:
        lines.append(
            "| slug | phrase | expected any of | observed tools |"
        )
        lines.append("|---|---|---|---|")
        for m in report["cross_check_mismatches"]:
            lines.append(
                f"| {m['slug']} | {m['phrase']} | {', '.join(m['expected_any_of'])} "
                f"| {', '.join(m['observed_tools'])} |"
            )
    else:
        lines.append(
            "No mismatches: every adjudication phrase with a keyword mapping has a "
            "matching observed tool call."
        )
    lines += [
        "",
        "## DRAFT evidence-kind proposal (for Checkpoint-1 ratification)",
        "",
        f"Thresholds: consult-rate ≥ {_REQUIRED_THRESHOLD:.0%} ⇒ required; "
        f"≥ {_OPTIONAL_THRESHOLD:.0%} ⇒ optional. Rates are lower bounds "
        "(max over the kind's mapped observation classes).",
        "",
        "**This is a machine draft.** `type_signature` consultation is not "
        "mechanically detectable from call inputs (it looks like `other_file` "
        "reads); review the latent_bug `other_file` rates and the adjudication "
        "notes before finalizing.",
        "",
        "| category | required | optional |",
        "|---|---|---|",
    ]
    for category, entry in report["draft_proposal"].items():
        required = [k for k, v in entry["kinds"].items() if v["tier"] == "required"]
        optional = [k for k, v in entry["kinds"].items() if v["tier"] == "optional"]
        lines.append(
            f"| {category} | {', '.join(required) or '—'} | {', '.join(optional) or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces-dir", type=Path, default=DEFAULT_TRACES)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries_by_slug = {e["slug"]: e for e in manifest["entries"]}

    mined: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for row in summary["rows"]:
        entry = entries_by_slug[row["slug"]]
        if not row["agree"]:
            reason = "gray" if entry.get("gray") else "verdict miss"
            excluded.append({"slug": row["slug"], "reason": reason})
            continue
        trace_path = args.traces_dir / f"{TRACE_PREFIX}{row['slug']}.json"
        record = json.loads(trace_path.read_text(encoding="utf-8"))
        mined.append(mine_trace(entry, record))

    by_category = aggregate(mined)
    report = {
        "summary_file": args.summary.name,
        "n_mined": len(mined),
        "excluded": excluded,
        "by_category": by_category,
        "draft_proposal": draft_proposal(by_category),
        "cross_check_mismatches": cross_check(
            {m["slug"]: m for m in mined}, manifest["entries"]
        ),
        "traces": mined,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "mining-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (args.out / "mining-report.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    print(f"mined {len(mined)} traces -> {args.out}")
    for category, stats in by_category.items():
        print(f"  {category}: n={stats['n_traces']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
