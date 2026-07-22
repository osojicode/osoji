"""work#59 rubric A/B: Significance as grade (demote-not-drop) vs three-predicate gate.

Replays the live ``.osoji/findings/`` debris corpus through the unified Triage
stage twice — identical claims, identical evidence, identical code; the ONLY
variable is ``system_prompt``:

  side A: THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT  (frozen pre-work#59 rubric:
          TP = Reality + Significance + Actionability, dismiss on any failure)
  side B: TRIAGE_SYSTEM_PROMPT                  (ruled rubric: TP = Reality +
          Actionability; Significance grades severity, real-but-minor -> info)

Both sides decide in production-bounded chunks (``decide_junk_claims``,
BATCH_SIZE=12, bisect on failure) per the v15e run-1 lesson.

The adjudicable signal (per JF's ruling, work#59): dismissals side A grounded
in Significance that side B converts to confirmed-at-info. Reality- and
Actionability-grounded dismissals should be stable across sides; churn there
is sampling noise, bounded by the control.

Variance control (wiki decisions/0016, decision 6): run with ``--control`` to
decide the corpus twice under side A's prompt — same prompt, same chunking —
before reading anything into the A/B delta.

Usage (from the branch checkout; --root points at a checkout holding the
corpus in .osoji/):

    PYTHONUTF8=1 python scripts/ab_v159_significance_grade.py \
        --root /path/to/repo \
        --out scratch/ab-v159-raw.json [--control]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from osoji.claim_builder import build_debris_claims  # noqa: E402
from osoji.config import Config  # noqa: E402
from osoji.llm.runtime import create_runtime  # noqa: E402
from osoji.triage import TRIAGE_SYSTEM_PROMPT  # noqa: E402

# Frozen copy of the pre-work#59 rubric this A/B measures against (the version
# shipped by V1-5e / osoji#120), so the gate script stays runnable after the
# rubric changes in triage.py.
THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT = """\
You are osoji's Triage stage: the single verifier for every code-quality finding.

Every finding is a hypothesis about a GAP between what the code claims and what it does:
- reachability — declared/claimed to be used, but actually unreachable
  (dead code, dead parameters, unactuated config, orphaned files, unused deps).
- description — described one way (comment, docstring, name, type), behaves another
  (stale comments, misleading docstrings, latent bugs that violate a stated contract).
- contract — an implicit cross-component agreement (shared string, schema, ABI) is broken
  (obligation violations, cross-file string drift).
- uncategorized — does not fit cleanly; decide on the merits and say so.

A finding is a TRUE POSITIVE iff all three predicates hold:
- Reality — the gap actually exists in the code (the evidence supports it).
- Significance — closing the gap improves the codebase; widening it would harm.
- Actionability — there is a concrete fix.
Confirm only when all three hold. Dismiss when any fails. Use 'uncertain' when the
assembled evidence genuinely cannot decide.

Weigh the assembled evidence. For reachability claims, a cross-file reference that is a
real import/call/use refutes the gap (dismiss); a reference that is only an unrelated
comment, a doc mention, or a same-named-but-different symbol does not (confirm). A hit
inside a quoted string (marked [match is inside a quoted string]) needs care: when the
flagged symbol's exact name appears as a string in executable code, it may be a
dynamic-dispatch key — reflection, name-based lookup, a registry, a command/RPC/config
table. Examine the surrounding lines; if the string plausibly feeds a mechanism that can
reach the symbol, the symbol is reachable — dismiss. Account for framework registration,
re-exports, and within-file transitive liveness. Do not dismiss on hypothetical outside
consumers: "external callers might use it" counts only when an explicit export mechanism
makes the symbol consumable beyond the scanned scope. When reachability evidence is
positive but marginal and the flagged symbol is a small delegating member of a uniform
interface surface, removing it is unlikely to improve the codebase — dismiss on
Significance. (Zero-hit sweeps carry no such doubt: an honest zero over a real scan
scope is the canonical case FOR confirming.)

For parameter reachability claims specifically: the parameter is alive iff some caller
supplies a real value (keyword, positional, or a spread/dynamic pass-through). Reads of
the parameter inside its own function — including branches guarded by its default — do
not refute the gap; a branch gated exclusively by a never-passed parameter is itself
permanently dead code, which is exactly the significance of the finding. A stated
backward-compatibility intent explains why the gap exists but does not close it.

For unactuated-config reachability claims specifically: the gap is about enforcement,
not mere reference. The field is alive only if some code uses its value to CAUSE the
declared effect (actuation). A reference that only reads, stores, forwards, restructures,
logs, or displays the value is NOT actuation and does not refute the gap — a value that
is plumbed everywhere but never reaches the enforcing operation leaves the obligation
unmet, and that unenforced obligation is the significance of the finding. Passing the
value to a component documented to enforce it — a library call, or a cross-process
handoff (env var → container → subprocess) — IS actuation when the receiving side
enforces. Confirm when the assembled references show the value flowing without any site
that enforces it.

An unactuated-config gap exists only for obligations the project itself declares. A
schema or field defined in vendored or third-party reference material — content the
project stores or mirrors but does not consume as its own configuration — creates no
obligation for this project to actuate; dismiss it regardless of reference counts, and
weigh whether the containing file participates in the project's own configuration
loading.

For orphaned-file reachability claims specifically: reachability can be file-level, not
only symbol-level. A whole file may be reached by convention rather than by an import
edge — discovered by a framework or tool (such as test, fixture, migration, or template
discovery), loaded dynamically, named in configuration or CI, or invoked as a script or
entry point. A missing import edge does not by itself confirm an orphan; confirm only
when no such conventional or dynamic pathway plausibly reaches the file. An honest zero
over a real sweep of the file's name and exported symbols is the case FOR confirming.

For dead-CI/CD reachability claims specifically: a missing referenced path is the
primary signal but not dispositive. Weigh whether the element's real work depends on the
missing path or merely mentions it among operations that are inherently external or
dynamically resolved (such as dependency installation, whole-repo linters, dynamic test
discovery, external deploy or registry targets, or conventional phony targets). An
element whose entire purpose rests on what is now gone is far more likely dead than one
that references the missing path incidentally; decide on the balance of the element's
dependence on what is actually missing.

For contract gaps over hard-coded literals, classify the literal before deciding:
- Named project obligation — a constant exists; another site duplicates its bare literal.
  Confirm; suggest using the existing constant.
- Unnamed project obligation — two sites share a bare literal in clearly-related roles, no
  constant yet. Confirm; suggest extracting a shared constant.
- Ecosystem convention — meaning defined outside the project (HTTP codes, file modes,
  MIME types, RFC strings). Dismiss; the contract is with the external standard.
- Magic-constant duplication (ambiguous) — examine: confirm if the sites should agree,
  dismiss if coincidental.
- Coincidental duplication — same literal, unrelated roles. Dismiss as coincidence.

For every contract-gap claim, emit a `contract_class` alongside the verdict — one of
named_obligation, unnamed_obligation, ecosystem_convention, magic_constant, coincidence,
or other. Reason over the whole assembled file tuple, not only the pair named in the
claim header: every file that produces, checks, or defines the shared literal rides along
with its surrounding code, and a third file that independently emits the same literal is
itself a drift risk even when the header names the best-attested coupling. Shared-literal
drift fails SILENTLY at the value level — a mismatched string, no error — and confirming
binds the sites to one definition so the next rename fails LOUDLY at the name level; that
conversion, not "extract a constant" for its own sake, is the significance. When the
literal fits none of the five classes, set `contract_class` to `other` and say why:
`other` is the taxonomy's safety valve — a request for review, never shoehorned into the
nearest class — and its rate is a tracked signal of the taxonomy's adequacy.

When a single claim bundles several shared literals for one file pair, judge the bundle by
its strongest constituent: if any bundled literal is a genuine project obligation (named or
unnamed), confirm the claim and set `contract_class` to that strongest class, noting in the
reasoning which literals carry the contract and which are incidental. Dismiss a bundle only
when every constituent literal is an ecosystem convention or coincidence.

A literal whose meaning is fixed by an external API, wire format, or protocol is an
ecosystem convention no matter which side of the boundary emitted it: a value your code
sends and a value it receives back are governed alike by the external contract, not by any
project obligation. Judge such strings by the protocol that defines them, and apply that
judgement consistently across the protocol's whole vocabulary — do not confirm one member
of an external message/status/finish-reason vocabulary while dismissing its siblings.

--- Description gaps in prose documentation (V1-5d) ---
For a description gap where the claim is that a documentation file (README, guide,
spec, or other prose that describes code behavior) contradicts what the code does,
weigh it against these principles:
- A description gap requires a positive assertion in the documentation that the code
  contradicts — the doc states something and the code does otherwise. The mere absence
  of a mention is not such a gap: that a doc could usefully describe something it
  currently omits is a coverage question, owned by a different subsystem, and is
  dismissed here no matter how valuable adding the mention would be. Adjudicate only
  what the doc affirmatively claims; never fault it for what it leaves unsaid.
- Shadow docs are compressed summaries, not exhaustive. A documented command, flag,
  config key, path, or entry point that is absent from a shadow doc is NOT thereby
  absent from the project — it may be defined in a file the summary omits (a config
  file, build manifest, registration table, or a sibling module). If the assembled
  cross-file evidence shows the documented thing genuinely exists, dismiss on Reality;
  confirm only when the evidence positively shows the doc is wrong.
- When counter-evidence is partial — the doc is imprecise but not plainly false —
  prefer keeping the finding at lower severity (warning) over dropping it; reserve
  dismissal for claims the evidence actively refutes.
- Documentation that describes intended, planned, or roadmap behavior is not a
  description gap merely because the current code does not yet implement it; dismiss
  unless the doc presents the behavior as already current.
- Deliberate simplification in learning-oriented material is not an inaccuracy; a
  tutorial that omits or streamlines detail to teach is correct for its purpose —
  confirm only when it states something false about current behavior.
- Illustrative example code is not a normative contract; divergence between an
  example and the implementation is not a gap unless the doc claims the example is
  exhaustive or authoritative.
--- end description-gap guidance ---

Capture your reasoning verbatim. Provide a verdict for EVERY claim."""

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from measure_debris_cutover import load_debris_ignoring_impl_hash  # noqa: E402


def _finding_row(finding) -> dict:
    return {
        "id": finding.id,
        "detector": finding.detector,
        "path": finding.path,
        "symbol": finding.symbol,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "contract_claim": finding.contract_claim,
        "verdict": finding.verdict,
        "confidence": finding.confidence,
        "severity": finding.severity,
        "reasoning": finding.triage_reasoning,
        "suggested_fix": finding.suggested_fix,
    }


async def _run_side(label: str, claims, config: Config, system_prompt: str) -> dict:
    """Decide the claims in production-bounded chunks (v15e run-1 lesson)."""

    from osoji.junk_triage import decide_junk_claims

    provider, _ = create_runtime(config)
    try:
        findings, in_tok, out_tok = await decide_junk_claims(
            list(claims), config, provider, system_prompt=system_prompt
        )
    finally:
        await provider.close()
    undecided = sum(1 for f in findings if f.verdict is None)
    severities = Counter(f.severity for f in findings if f.verdict == "confirmed")
    print(
        f"[{label}] {len(findings)} findings decided, {undecided} undecided, "
        f"confirmed severities {dict(severities)}, tokens {in_tok}^ {out_tok}v",
        flush=True,
    )
    return {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "undecided": undecided,
        "confirmed_severities": dict(severities),
        "verdict_counts": dict(Counter(f.verdict for f in findings)),
        "findings": [_finding_row(f) for f in findings],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="checkout holding .osoji/ with the corpus")
    parser.add_argument("--out", default="scratch/ab-v159-raw.json")
    parser.add_argument(
        "--control", action="store_true",
        help="variance control: decide the corpus twice under side A's prompt "
             "(same prompt, same chunking) instead of running the A/B",
    )
    args = parser.parse_args()

    load_dotenv(Path(args.root) / ".env")

    config = Config(
        root_path=Path(args.root),
        provider="anthropic",
        respect_gitignore=False,
        quiet=True,
    )
    raw_debris = load_debris_ignoring_impl_hash(config)
    claims, original_indices, would_escalate = build_debris_claims(config, raw_debris)
    print(
        f"corpus: {len(raw_debris)} raw debris findings, {len(claims)} eligible claims, "
        f"{would_escalate} would-escalate (kept unverified)",
        flush=True,
    )
    if not claims:
        raise SystemExit("no claims — corpus missing?")

    if args.control:
        side_a = asyncio.run(_run_side("A control-1", claims, config, THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT))
        side_b = asyncio.run(_run_side("A control-2", claims, config, THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT))
        labels = ("control_1", "control_2")
    else:
        side_a = asyncio.run(_run_side("A three-predicate", claims, config, THREE_PREDICATE_TRIAGE_SYSTEM_PROMPT))
        side_b = asyncio.run(_run_side("B grade-not-gate", claims, config, TRIAGE_SYSTEM_PROMPT))
        labels = ("side_a_three_predicate", "side_b_grade_not_gate")

    changed = []
    demotions = []  # the ruling's target class: A dismissed -> B confirmed at info
    for row_a, row_b in zip(side_a["findings"], side_b["findings"]):
        assert row_a["id"] == row_b["id"]
        if row_a["verdict"] != row_b["verdict"]:
            entry = {
                "id": row_a["id"],
                "detector": row_a["detector"],
                "path": row_a["path"],
                "symbol": row_a["symbol"],
                "lines": [row_a["line_start"], row_a["line_end"]],
                "claim": row_a["contract_claim"],
                labels[0]: {k: row_a[k] for k in ("verdict", "confidence", "severity", "reasoning")},
                labels[1]: {k: row_b[k] for k in ("verdict", "confidence", "severity", "reasoning")},
            }
            changed.append(entry)
            if row_a["verdict"] == "dismissed" and row_b["verdict"] == "confirmed" \
                    and row_b["severity"] == "info":
                demotions.append(entry)

    out = {
        "mode": "control" if args.control else "ab",
        "corpus_size": len(claims),
        "would_escalate": would_escalate,
        "changed_verdict_count": len(changed),
        "dismissed_to_confirmed_info_count": len(demotions),
        "changed": changed,
        labels[0]: side_a,
        labels[1]: side_b,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nchanged verdicts: {len(changed)}/{len(claims)}")
    if not args.control:
        print(f"dismissed -> confirmed@info (the ruling's target class): {len(demotions)}")
    for ch in changed:
        a, b = ch[labels[0]], ch[labels[1]]
        print(f"  {ch['detector']} {ch['path']}:{ch['lines'][0]} {ch['symbol'] or ''}: "
              f"{a['verdict']} -> {b['verdict']} (sev {a['severity']} -> {b['severity']})")
    print(f"raw results: {out_path}")


if __name__ == "__main__":
    main()
