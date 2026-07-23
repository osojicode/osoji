"""Unified Triage stage for the osoji v1 architecture (V1-3).

Triage is the single evidence-weighted verifier that replaces osoji's six+
scattered per-detector verification gates. It consumes a batch of self-sufficient
:class:`Claim`s — :class:`~osoji.findings.Finding`s whose :class:`~osoji.evidence.Evidence`
has been assembled by a Claim Builder — and fills each finding's triage outputs
(``verdict`` / ``confidence`` / ``triage_reasoning`` / ``suggested_fix`` / ``severity``).

See ``osojicode/wiki`` ``specs/0001-v1-foundation.md`` (*The Triage stage (B)*),
``concepts/self-sufficient-claims.md``, ``concepts/three-gap-theory.md``, and
``concepts/string-contract-taxonomy.md``.

Two modes:

- **claim mode** (default): one forced-tool LLM call decides the whole batch.
  Bounded token cost — no exploration. The production path.
- **exploration mode**: a per-claim multi-turn loop where the LLM is given
  read-only ``read_file`` / ``grep`` / ``list_dir`` tools (see
  :class:`~osoji.triage_exec.ExplorationExecutor`) and decides with retrieval.
  Used by the V1-4 Claim-Builder bootstrap and by per-claim escalation.

The **rubric is an input prompt**, not baked into the stage: ``decide_batch``
takes a ``system_prompt``. Every production path now passes the canonical
unified rubric (:data:`TRIAGE_SYSTEM_PROMPT`). Phase 3 debris was the last
holdout on the preserved legacy prompt (decision 0014's re-plumbing seam); it
flipped in V1-5e (work#52) gated by a same-claims A/B — see
``tests/fixtures/bootstrap/ab-v15e-report.md``.

Incremental-audit hook (V1-9): ``decide_batch`` accepts an optional verdict cache
keyed by ``(finding.id, evidence_fingerprint)``. A claim whose key hits the cache
reuses the cached verdict and **skips the LLM**. A ``None`` evidence_fingerprint is
cache-ineligible (always triaged) — never a key value — so two no-fingerprint
findings that collide on ``id`` cannot reuse a stale verdict.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Any

from .config import Config
from .evidence import Evidence
from .findings import Finding
from .llm.runtime import create_runtime
from .llm.types import CompletionOptions, Message, MessageRole
from .tools import (
    get_triage_claim_tool_definitions,
    get_triage_exploration_tool_definitions,
)
from .triage_exec import ExplorationExecutor

# The canonical unified rubric — three-gap predicates + gap-type guidance + the
# five-class string-contract sub-rubric. This is the spec's single largest
# optimization target. Every production Triage path passes it since V1-5e
# retired the legacy debris prompt (A/B evidence: ab-v15e-report.md).
#
# Assembled from named sections — one principle per section — so
# leave-one-section-out ablations and per-section optimization can target them
# (wiki decisions/0022, work#66). Assembly is byte-identical to the
# pre-sectioning literal; tests/test_triage_sectioning.py pins the sha256.
TRIAGE_PROMPT_SECTIONS: dict[str, str] = {
    "mission": """\
You are osoji's Triage stage: the single verifier for every code-quality finding.

Every finding is a hypothesis about a GAP between what the code claims and what it does:
- reachability — declared/claimed to be used, but actually unreachable
  (dead code, dead parameters, unactuated config, orphaned files, unused deps).
- description — described one way (comment, docstring, name, type), behaves another
  (stale comments, misleading docstrings, latent bugs that violate a stated contract).
- contract — an implicit cross-component agreement (shared string, schema, ABI) is broken
  (obligation violations, cross-file string drift).
- uncategorized — does not fit cleanly; decide on the merits and say so.

""",
    "predicates": """\
A finding is a TRUE POSITIVE iff both predicates hold:
- Reality — the gap actually exists in the code, NOW: the mismatch the claim
  asserts is exhibited by the artifacts under audit, checkable against the
  checkout without hypothesizing states the repository might reach. A claim
  that quantifies over hypothetical states — edits not yet made, input classes
  no artifact produces, configurations no file contains — fails Reality, not
  because it is minor but because that space is unbounded. Judge what the
  claim asserts: a claim asserting a failure needs the failure's premise
  exhibited; a claim asserting a mismatch (a dead invocation, a lying label,
  contradictory declarations) needs only the mismatch exhibited, reachable
  harm or not. A mismatch that is already resolved in the checkout is history,
  not a current gap. Code that matches its own documented, intended design is
  not a gap — an intent-documented behavior fails Reality, however improvable
  it may be. So does a not-yet-real observation: future fragility or
  robustness advice about code that currently behaves correctly describes a
  gap that does not exist yet.
- Actionability — there is a concrete fix.
Confirm when both hold. Dismiss when either fails. Use 'uncertain' when the
assembled evidence genuinely cannot decide. When the defect at the cited site
is real but the finding's remediation points the wrong way — the wrong artifact
of a cross-artifact contradiction, an inverted fix direction — confirm, supply
the corrected direction in `suggested_fix`, and note the reframe in your
reasoning; when the cited site contains no defect, dismiss — a different
defect elsewhere is a new finding, not a rescue. A 'confirmed' verdict asserts
exactly one thing: the finding's claim about the code is true — if your
reasoning concludes the claim fails, the matching verdict is 'dismissed',
never 'confirmed'.

""",
    "significance": """\
Significance GRADES a confirmed finding; it never gates one. Set severity by how much
closing the gap improves the codebase: 'error' when the gap corrupts behavior or
misleads (silent contract breaks, docs that state falsehoods), 'warning' for the
typical real gap, 'info' when the gap is real and fixable but minor. Never dismiss a
real, actionable finding for being minor — it is not Triage's job to adjudicate
between correct findings; ordering work belongs to the consumer of the report.
Fallbacks, guards, invocation conventions, and blast-radius arguments are
Significance inputs only: they grade severity, never existence. Grade masking
on a ladder: a gap fully masked or convention-guarded grades 'info'; one
reachable under plausible non-default use grades 'warning'; one reachable in
normal use grades by impact.

""",
    "reachability_weighing": """\
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
interface surface, the mechanism that reaches its siblings plausibly reaches it too —
the gap's Reality is not established; dismiss on Reality, not on the smallness of the
win. (Zero-hit sweeps carry no such doubt: an honest zero over a real scan scope is
the canonical case FOR confirming — and a confirmed minor gap grades 'info', it does
not get dismissed.)

""",
    "parameter": """\
For parameter reachability claims specifically: the parameter is alive iff some caller
supplies a real value (keyword, positional, or a spread/dynamic pass-through). Reads of
the parameter inside its own function — including branches guarded by its default — do
not refute the gap; a branch gated exclusively by a never-passed parameter is itself
permanently dead code, which is exactly the significance of the finding. A stated
backward-compatibility intent explains why the gap exists but does not close it.

""",
    "unactuated_config": """\
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

""",
    "vendored_material": """\
An unactuated-config gap exists only for obligations the project itself declares. A
schema or field defined in vendored or third-party reference material — content the
project stores or mirrors but does not consume as its own configuration — creates no
obligation for this project to actuate; dismiss it regardless of reference counts, and
weigh whether the containing file participates in the project's own configuration
loading.

""",
    "orphaned_file": """\
For orphaned-file reachability claims specifically: reachability can be file-level, not
only symbol-level. A whole file may be reached by convention rather than by an import
edge — discovered by a framework or tool (such as test, fixture, migration, or template
discovery), loaded dynamically, named in configuration or CI, or invoked as a script or
entry point. A missing import edge does not by itself confirm an orphan; confirm only
when no such conventional or dynamic pathway plausibly reaches the file. An honest zero
over a real sweep of the file's name and exported symbols is the case FOR confirming.

""",
    "dead_cicd": """\
For dead-CI/CD reachability claims specifically: a missing referenced path is the
primary signal but not dispositive. Weigh whether the element's real work depends on the
missing path or merely mentions it among operations that are inherently external or
dynamically resolved (such as dependency installation, whole-repo linters, dynamic test
discovery, external deploy or registry targets, or conventional phony targets). An
element whose entire purpose rests on what is now gone is far more likely dead than one
that references the missing path incidentally; decide on the balance of the element's
dependence on what is actually missing.

""",
    "contract_classes": """\
For a contract gap, classify by WHO DEFINES THE BINDING the claim rests on — never by what
carries it. A shared literal, a payload shape, a wire format, a filesystem layout, a naming
convention are all just carriers; the carrier never decides the class, only the source of
authority and the repayment action that would retire the debt do:
- project_named — the project defines the binding EXPLICITLY somewhere: a constant, a
  schema file, a declared type, a documented invariant; the claim is a site drifting from
  (or duplicating instead of using) that definition. Repayment verb BIND — point the site
  at the existing definition. This class requires a bindable artifact: a name, schema, or
  type a drifting site could actually reference. Prose (a comment, a doc) declares intent
  but does not name a binding, so a prose-only invariant is never project_named.
- project_implicit — components of this project agree in behavior, but the agreement is
  written down nowhere shared: a bare value two files must keep equal, a payload shape one
  file produces and another assumes, a tokenizer/parser handshake, name-string dispatch.
  Repayment verb DECLARE — create the missing shared definition (constant, schema, type)
  so future drift fails LOUDLY at the name level instead of silently at the value level.
- ecosystem — an EXTERNAL standard, protocol, or tool fixes the meaning (HTTP codes, SSE
  framing, coverage-tool JSON, package-manager layout, MCP envelope). External authority
  wins even when the project also wraps the value. Such a binding is DEBT only via the
  project's own adoption claim — the project says or implies it speaks this protocol;
  violating an adopted standard confirms with repayment verb CONFORM (or an explicitly
  declared deviation). A bare use of the standard's vocabulary with no violation and no
  project-level agreement is not the project's to define: dismissal territory.
- coincidental — no binding exists; the resemblance between sites is accidental, no
  contradiction is possible, hence no debt. Repayment verb CLOSE.

""",
    "contract_verdict": """\
For every contract-gap claim, emit a `contract_class` alongside the verdict — one of
project_named, project_implicit, ecosystem, coincidental, or other. Emission is not
optional on a contract-gap claim: omitting the field is itself an error, never a way to
signal uncertainty about the class. Reason over the whole assembled file tuple, not only
the pair named in the claim header: every file that produces, checks, or defines the
shared binding rides along with its surrounding code, and a third file that independently
emits the same value is itself a drift risk even when the header names the best-attested
coupling. Cross-site drift fails SILENTLY at the value level — a mismatched value, no
error — and confirming binds the sites to one definition so the next rename fails LOUDLY at
the name level; that conversion, not "extract a constant" for its own sake, is the
significance. When none of the four repayment actions (BIND / DECLARE / CONFORM / CLOSE)
would retire the case, set `contract_class` to `other` and say what is binding-like about
it yet unclassifiable: `other` is the taxonomy's safety valve — a request for review, never
shoehorned into the nearest class — and its rate is a tracked signal of the taxonomy's
adequacy.

""",
    "contract_bundles": """\
When a single claim bundles several shared bindings for one file pair, judge the bundle by
its strongest constituent, in precedence order project_named > project_implicit > ecosystem
> coincidental: if any bundled binding is a genuine project obligation (project_named or
project_implicit), confirm the claim and set `contract_class` to that strongest class,
noting in the reasoning which bindings carry the contract and which are incidental. Dismiss
a bundle only when every constituent is an ecosystem binding (with no adoption-claim
violation) or coincidental.

""",
    "contract_ecosystem_boundary": """\
A binding whose meaning is fixed by an external API, wire format, or protocol is
`ecosystem` no matter which side of the boundary emitted it: a value your code sends and a
value it receives back are governed alike by the external contract, not by any project
obligation. Judge such values by the protocol that defines them, and apply that judgement
consistently across the protocol's whole vocabulary — do not confirm one member of an
external message/status/finish-reason vocabulary while dismissing its siblings.

""",
    "latent_bug": """\
A latent-bug claim asserts the code can currently misbehave. Confirm one only
when you can state the concrete trigger — the specific input, state, or call
sequence that reaches the failure, and the wrong outcome it produces. If no
such path can be stated from the assembled evidence — the failure sits behind
a guard that already handles it, or requires a state the program cannot
reach — the gap is not real NOW: dismiss on Reality, or use 'uncertain' when
the evidence genuinely cannot decide. A deliberately pinned value asserted in
a test-role file (a snapshot pin, a golden value, a self-test expectation) is
a guard doing its job, not a magic-number bug: read it as declared intent for
the pinned value, scoped to files whose role is verification.
When such a claim's header shows gap type [uncategorized], also emit `gap_type`
classifying which invariant the alleged bug violates: one stated in an artifact
(comment, docstring, type, documentation) is a description gap; one that lives
only in an implicit cross-component agreement (a shared literal, schema, or
ABI) is a contract gap. Keep `uncategorized` when neither can be stated — that
is the honest outlet, not a failure.

""",
    "description_debris": """\
--- Description gaps in code artifacts ---
For a description gap where the claim is that a declaration inside a code
artifact — a comment, docstring, identifier, or other human-authored
annotation — contradicts what the code does, weigh it against these
principles:
- Adjudicate exactly the claim the finding packages, against the exact text of
  the cited declaration. Never refute a claim the declaration does not make,
  and never substitute an omission complaint for the packaged claim — that a
  declaration could usefully say more is a coverage question, dismissed here
  no matter how valuable the addition would be.
- Staleness asserts drift: the code moved away from what the declaration says.
  A declaration that was imprecise from the day it was written has not
  drifted. When the imprecision is nonetheless a real, fixable mismatch,
  confirm and grade 'info'; when the declaration is merely loose but not
  wrong, dismiss.
- The documented side of the comparison must be a declaration. Derived
  artifacts — summaries produced by observing the code — never constitute the
  documented claim; at most they relay a declaration, and their paraphrase is
  not evidence of drift. Before declaring a contradiction, trace the cited
  code's own mechanics in the evidence, including nested and error-path
  behavior: a declaration that accurately describes a mechanism you have not
  fully traced is the canonical false positive.
- Distinguish durable rationale from ephemeral process residue. A declaration
  recording design justification or the reason a safeguard exists is accurate
  history; its age is not drift, and removing it destroys signal. A tag
  pointing at a process artifact that no longer resolves is removable residue.
  Neither is a description gap unless the code contradicts what it says.
- If the finding's own reasoning concedes the cited declaration is accurate
  and pivots to a different claim — a cross-file assertion, a liveness claim
  owned by another detector — the packaged gap fails Reality: dismiss.
- A work-marker that records planned-and-forgotten work is a description gap
  when its subject is genuinely obsolete or done; one that states a
  deliberate, explained scope boundary is a documented limitation, not
  forgotten work. Both can be real — grade urgency instead of gating: markers
  carrying dates, ticket references, or fix-me urgency grade higher; an
  explained unimplemented branch grades 'info'.
--- end description-debris guidance ---

""",
    "prose_doc_gaps": """\
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

""",
    "closing": """\
Capture your reasoning verbatim. Provide a verdict for EVERY claim.""",
}

TRIAGE_SYSTEM_PROMPT = "".join(TRIAGE_PROMPT_SECTIONS.values())


def render_triage_prompt(omit: Collection[str] = ()) -> str:
    """Assemble the rubric with the named sections omitted (ablation variants).

    Unknown names raise ValueError so an ablation-config typo cannot silently
    produce a full-rubric arm.
    """
    unknown = set(omit) - TRIAGE_PROMPT_SECTIONS.keys()
    if unknown:
        raise ValueError(f"unknown rubric sections: {sorted(unknown)}")
    return "".join(
        text for name, text in TRIAGE_PROMPT_SECTIONS.items() if name not in omit
    )



@dataclass
class Claim:
    """A self-sufficient claim: a Finding plus the escalation flag.

    Thin by design — the Evidence lives on ``finding.evidence`` (the V1-2 schema
    field), so V1-4's mechanized Claim Builder populates the same place. The
    ``insufficient_evidence`` flag marks a claim the Claim Builder could not fill;
    Triage escalates it to exploration mode only when escalation is enabled (off
    in the V1-3 production debris path — decision 1).
    """

    finding: Finding
    insufficient_evidence: bool = False


@dataclass
class TriageBatchResult:
    """Outcome of a :meth:`Triage.decide_batch` call."""

    findings: list[Finding]
    input_tokens: int = 0
    output_tokens: int = 0
    verdict_cache_hit_rate: float = 0.0
    would_escalate_count: int = 0
    exploration_traces: list[dict[str, Any]] = field(default_factory=list)


# Hard ceiling on exploration turns per claim, so a runaway loop can't spend
# unbounded tokens. Reaching it yields an 'uncertain' verdict.
_MAX_EXPLORATION_TURNS = 8


def _maintainer_intent_block(project_rules: str) -> str:
    """Frame maintainer-declared project rules for the Triage user message.

    The rules are the maintainers' own statement of intended design, weighed as
    declared intent (decisions/0021 sense) — evidence to reason over, never a
    catalog of per-case verdict instructions or a mechanical suppression list.
    The framing is ours and deliberately short; the rules text rides through
    verbatim as user content.
    """

    return (
        "## Maintainer-declared project rules\n"
        "The project maintainers have declared the rules below. Weigh them as "
        "declared intent — the project's own statement of intended design — when "
        "deciding a finding's Reality, not as per-case verdict instructions: they "
        "are evidence to reason over, never a directive to confirm or dismiss any "
        "particular claim.\n"
        "--- begin maintainer-declared rules ---\n"
        f"{project_rules}\n"
        "--- end maintainer-declared rules ---\n\n"
    )


def _claim_echo(finding: Finding) -> str:
    """Identity token a batch verdict must echo back (cross-wiring guard).

    The claim's symbol when it has one; otherwise a ``path:line`` fallback so
    symbol-less claims (debris) still carry an identity the completeness
    validator can check (work#57 — the V1-5e A/B saw off-by-one verdicts
    survive validation because ``symbol=None`` left nothing to compare).
    """
    if finding.symbol:
        return finding.symbol
    if finding.line_start:
        return f"{finding.path}:{finding.line_start}"
    return finding.path


class Triage:
    """The unified Triage stage.

    A provider may be injected (tests); otherwise one is created per
    ``decide_batch`` call via :func:`create_runtime` and closed afterwards.
    """

    def __init__(
        self,
        config: Config,
        rate_limiter: Any | None = None,
        *,
        executor: ExplorationExecutor | None = None,
        provider: Any | None = None,
    ) -> None:
        self.config = config
        self.rate_limiter = rate_limiter
        self.executor = executor or ExplorationExecutor(config)
        self._provider = provider

    async def decide_batch(
        self,
        claims: list[Claim],
        *,
        mode: str = "claim",
        system_prompt: str = TRIAGE_SYSTEM_PROMPT,
        project_rules: str | None = None,
        verdict_cache: dict[tuple[str, str], dict] | None = None,
        escalate_insufficient: bool = False,
    ) -> TriageBatchResult:
        """Decide a batch of claims, filling each finding's triage outputs.

        - ``mode="claim"``: non-cache, non-escalated claims are decided by one
          batched LLM call.
        - ``mode="exploration"``: every non-cache claim is decided by a per-claim
          exploration loop.
        - Cache hits (non-None fingerprint whose ``(id, fingerprint)`` is in
          ``verdict_cache``) reuse the cached verdict and skip the LLM.
        - ``insufficient_evidence`` claims escalate to exploration only when
          ``escalate_insufficient`` is True; otherwise they pass through
          unverified (verdict stays ``None``). The count is always reported.

        ``project_rules`` (work#35): non-empty maintainer-declared project rules
        are prepended, in a clearly-delimited block, to the USER message (before
        the claims) so Triage can weigh them as declared intent. The SYSTEM
        prompt is untouched — the sectioning sha pin and the ablation harness are
        unaffected. Absent/blank rules leave the user message byte-identical to a
        no-rules run. Because the rules ride in the user message, callers fold a
        hash of the same text into ``audit_manifest.current_version()`` so cached
        verdicts invalidate when the rules change.
        """

        n = len(claims)
        findings: list[Finding] = [c.finding for c in claims]
        would_escalate = sum(1 for c in claims if c.insufficient_evidence)
        cache = verdict_cache or {}
        cache_hits = 0

        claim_route: list[tuple[int, Claim]] = []
        explore_route: list[tuple[int, Claim]] = []
        for idx, claim in enumerate(claims):
            fp = claim.finding.evidence_fingerprint
            if fp is not None and (claim.finding.id, fp) in cache:
                findings[idx] = _apply_cached(claim.finding, cache[(claim.finding.id, fp)])
                cache_hits += 1
                continue
            if mode == "exploration":
                explore_route.append((idx, claim))
            elif claim.insufficient_evidence:
                if escalate_insufficient:
                    explore_route.append((idx, claim))
                # else: pass-through, verdict stays None (decision 1)
            else:
                claim_route.append((idx, claim))

        in_tok = out_tok = 0
        traces: list[dict[str, Any]] = []

        if claim_route or explore_route:
            provider, owns = self._get_provider()
            try:
                if claim_route:
                    decided, ti, to = await self._run_claim_batch(
                        [c for _, c in claim_route], system_prompt, provider,
                        project_rules=project_rules,
                    )
                    for (idx, _), fnd in zip(claim_route, decided):
                        findings[idx] = fnd
                    in_tok += ti
                    out_tok += to
                for idx, claim in explore_route:
                    fnd, ti, to, trace = await self._run_exploration(
                        claim, system_prompt, provider, project_rules=project_rules,
                    )
                    findings[idx] = fnd
                    in_tok += ti
                    out_tok += to
                    traces.append(trace)
            finally:
                if owns:
                    await provider.close()

        # osojicode/work#35: the audit orchestrator may attach a decided-
        # findings ledger to config (mirrors the V1-9 verdict_session attach
        # in junk_triage.py) so `osoji corpus emit` can later snapshot any
        # decided finding into a corpus-case stub. getattr-safe so direct
        # decide_batch callers (most unit tests) are unaffected.
        ledger = getattr(self.config, "decided_ledger", None)
        if ledger is not None:
            ledger.extend(f.to_dict() for f in findings)

        hit_rate = cache_hits / n if n else 0.0
        return TriageBatchResult(
            findings=findings,
            input_tokens=in_tok,
            output_tokens=out_tok,
            verdict_cache_hit_rate=hit_rate,
            would_escalate_count=would_escalate,
            exploration_traces=traces,
        )

    # -- provider ----------------------------------------------------------

    def _get_provider(self) -> tuple[Any, bool]:
        """Return (provider, owns). Injected providers are not owned/closed."""

        if self._provider is not None:
            return self._provider, False
        provider, _ = create_runtime(self.config, rate_limiter=self.rate_limiter)
        return provider, True

    # -- claim mode --------------------------------------------------------

    async def _run_claim_batch(
        self,
        claims: list[Claim],
        system_prompt: str,
        provider: Any,
        *,
        project_rules: str | None = None,
    ) -> tuple[list[Finding], int, int]:
        n = len(claims)
        user = self._render_claim_batch(claims)
        if project_rules and project_rules.strip():
            user = _maintainer_intent_block(project_rules) + user

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "submit_triage_verdicts":
                return []
            verdicts = tool_input.get("verdicts", [])
            # Models occasionally emit the array JSON-encoded as one string,
            # or entries as bare strings (observed in live corpus replays);
            # malformed shape must re-ask, never raise.
            if not isinstance(verdicts, list):
                return [
                    "'verdicts' must be a JSON array of verdict objects "
                    f"(got {type(verdicts).__name__}); resubmit as structured objects"
                ]
            malformed = [
                f"index {j} is a {type(v).__name__}"
                for j, v in enumerate(verdicts)
                if not isinstance(v, dict)
            ]
            if malformed:
                return [
                    "non-object entries in 'verdicts' ("
                    + "; ".join(malformed)
                    + "); every entry must be a verdict object"
                ]
            by_index = {v.get("batch_index"): v for v in verdicts}
            errors = [
                f"Missing verdict for batch_index {i}" for i in range(n) if i not in by_index
            ]
            # Symbol echo guard: sibling claims (two params of one function)
            # are easy to cross-wire by index alone — a mismatched echo means
            # the verdict was written about a different claim. Symbol-less
            # claims (debris) are guarded by their path:line fallback echo.
            for i, claim in enumerate(claims):
                echoed = (by_index.get(i) or {}).get("symbol")
                expected = _claim_echo(claim.finding)
                if echoed and expected and echoed != expected:
                    errors.append(
                        f"Verdict for batch_index {i} echoes symbol '{echoed}' but "
                        f"claim {i} is `{expected}` — re-check your batch_index assignment"
                    )
            return errors

        result = await provider.complete(
            messages=[Message(role=MessageRole.USER, content=user)],
            system=system_prompt,
            options=CompletionOptions(
                model=self.config.model_for("medium"),
                # 500/claim: the rubric asks for verbatim reasoning per verdict,
                # and API providers enforce max_tokens hard — the V1-3 200/claim
                # allowance truncated tool JSON mid-batch on the anthropic
                # provider (V1-5a fixture gate), which the claude-code CLI's
                # soft handling had masked.
                max_tokens=max(1024, n * 500),
                reservation_key="audit.triage",
                tools=get_triage_claim_tool_definitions(),
                tool_choice={"type": "tool", "name": "submit_triage_verdicts"},
                tool_input_validators=[check_completeness],
            ),
        )

        verdict_by_index: dict[int, dict] = {}
        for tc in result.tool_calls:
            if tc.name == "submit_triage_verdicts":
                raw = tc.input.get("verdicts", [])
                # Defense in depth behind the validator: a provider without
                # validator support can still hand back malformed entries;
                # skip them (undecided) rather than crash the whole batch.
                for v in raw if isinstance(raw, list) else []:
                    if not isinstance(v, dict):
                        continue
                    bi = v.get("batch_index")
                    if bi is not None:
                        verdict_by_index[bi] = v

        decided = [
            _apply_verdict(c.finding, verdict_by_index[i]) if i in verdict_by_index else c.finding
            for i, c in enumerate(claims)
        ]
        return decided, result.input_tokens, result.output_tokens

    def _render_claim_batch(self, claims: list[Claim]) -> str:
        parts = ["## Claims to triage\n"]
        for i, claim in enumerate(claims):
            parts.append(self._render_claim_block(i, claim.finding))
        parts.append(
            f"\nProvide a verdict for EVERY claim (batch indices 0..{len(claims) - 1}) "
            "using the submit_triage_verdicts tool, echoing each claim's Symbol line "
            "in the verdict's symbol field."
        )
        return "\n".join(parts)

    @staticmethod
    def _render_claim_block(index: int, finding: Finding) -> str:
        loc = finding.path
        if finding.line_start:
            loc += f":L{finding.line_start}-{finding.line_end}"
        lines = [f"### Claim {index}: {finding.detector} [{finding.gap_type}] — {loc}"]
        lines.append(f"Symbol: `{_claim_echo(finding)}`")
        lines.append(f"Claim ({finding.contract_source}): {finding.contract_claim}")
        lines.append(f"Observed: {finding.observed_behavior}")
        if finding.evidence:
            lines.append("Evidence:")
            for ev in finding.evidence:
                lines.append(_render_evidence(ev))
        lines.append("")
        return "\n".join(lines)

    # -- exploration mode (implemented in V1-3 task #5) --------------------

    async def _run_exploration(
        self,
        claim: Claim,
        system_prompt: str,
        provider: Any,
        *,
        project_rules: str | None = None,
    ) -> tuple[Finding, int, int, dict[str, Any]]:
        """Decide one claim via a multi-turn read/grep/list loop.

        The model is given the claim plus read-only retrieval tools and a terminal
        ``submit_triage_verdict`` tool. Every tool call is recorded to the trace
        (persisted for corpus building and debugging). Reaching the turn limit
        without a verdict yields ``uncertain``. Tool results are fed back as
        Anthropic content blocks — the provider passes ``Message.content``
        straight through (see
        ``llm/anthropic.py``), so assistant ``tool_use`` and user ``tool_result``
        blocks round-trip without a dedicated message role.
        """

        finding = claim.finding
        user = (
            self._render_claim_block(0, finding)
            + "\nExplore the repository with read_file / grep / list_dir as needed, "
            "then call submit_triage_verdict with your decision."
        )
        if project_rules and project_rules.strip():
            user = _maintainer_intent_block(project_rules) + user
        messages: list[Message] = [Message(role=MessageRole.USER, content=user)]
        trace: dict[str, Any] = {"finding_id": finding.id, "calls": []}
        tools = get_triage_exploration_tool_definitions()
        in_tok = out_tok = 0
        verdict: dict | None = None

        for turn in range(_MAX_EXPLORATION_TURNS):
            result = await provider.complete(
                messages=messages,
                system=system_prompt,
                options=CompletionOptions(
                    model=self.config.model_for("medium"),
                    max_tokens=2048,
                    reservation_key="audit.triage.explore",
                    tools=tools,
                    tool_choice={"type": "auto"},
                ),
            )
            in_tok += result.input_tokens
            out_tok += result.output_tokens
            if not result.tool_calls:
                break  # model answered in prose / gave up

            assistant_content: list[dict[str, Any]] = []
            if result.content:
                assistant_content.append({"type": "text", "text": result.content})
            for tc in result.tool_calls:
                assistant_content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                )
            messages.append(Message(role=MessageRole.ASSISTANT, content=assistant_content))

            for tc in result.tool_calls:
                trace["calls"].append({"turn": turn, "name": tc.name, "input": tc.input})
                if tc.name == "submit_triage_verdict":
                    verdict = tc.input
            if verdict is not None:
                break

            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": self.executor.run(tc.name, tc.input),
                }
                for tc in result.tool_calls
            ]
            messages.append(Message(role=MessageRole.USER, content=tool_results))

        if verdict is not None:
            decided = _apply_verdict(finding, verdict)
        else:
            decided = replace(
                finding,
                verdict="uncertain",
                confidence=0.0,
                triage_reasoning="Exploration did not produce a verdict within the turn limit.",
            )
        return decided, in_tok, out_tok, trace


# -- module helpers --------------------------------------------------------


_DISMISSAL_WORD = re.compile(r"\bdismiss\w*\b", re.IGNORECASE)
_CONFIRM_WORD = re.compile(r"\bconfirm\w*\b", re.IGNORECASE)
_NEGATION_WORD = re.compile(
    r"\b(?:not|no|none|nothing|never|nor|cannot|can't|don't|doesn't|won't"
    r"|wouldn't|without|than|instead|rather|avoid\w*|refus\w*)\b",
    re.IGNORECASE,
)


def _reasoning_contradicts_verdict(verdict: str | None, reasoning: str | None) -> bool:
    """True when the reasoning's closing statement asserts the opposite verdict.

    The observed failure mode (work#78) is a reasoning that ends "Dismissing on
    Reality" shipped under ``verdict=confirmed``. Only the final sentence is
    examined — that is where the rubric's verdict statement lands — and a
    negation before the verdict word ("nothing justifies dismissing") means the
    sentence rejects that verdict rather than stating it. High precision over
    recall: the guard must never demote a verdict whose reasoning merely
    discusses the opposite outcome.
    """

    if verdict == "confirmed":
        opposite = _DISMISSAL_WORD
    elif verdict == "dismissed":
        opposite = _CONFIRM_WORD
    else:
        return False
    if not reasoning:
        return False
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", reasoning.strip()) if s.strip()]
    if not sentences:
        return False
    last = sentences[-1]
    m = opposite.search(last)
    if not m:
        return False
    return not _NEGATION_WORD.search(last[: m.start()])


# LLM-assigned gap_type split (decisions/0025): only claims the mechanical
# layer parked as ``uncategorized`` may be re-routed, and only to these values.
_GAP_SPLIT_ALLOWED = frozenset({"description", "contract", "uncategorized"})


def _split_gap_type(finding: Finding, assigned: Any) -> str:
    """The gap_type to persist: LLM split applies only to parked claims."""

    if finding.gap_type == "uncategorized" and assigned in _GAP_SPLIT_ALLOWED:
        return assigned
    return finding.gap_type


def _apply_verdict(finding: Finding, v: dict) -> Finding:
    """Return a copy of ``finding`` with triage outputs from a verdict dict.

    Routes verdict/reasoning contradictions to ``uncertain`` (work#78) — a
    review flag, never a suppression. ``_apply_cached`` replays entries that
    already passed this guard when first decided, so it stays unguarded.
    """

    verdict = v.get("verdict")
    reasoning = v.get("reasoning")
    if _reasoning_contradicts_verdict(verdict, reasoning):
        verdict = "uncertain"
        reasoning = (
            f"{reasoning} [triage-guard: reasoning contradicts the submitted "
            f"'{v.get('verdict')}' verdict; routed to uncertain for review]"
        )
    return replace(
        finding,
        verdict=verdict,
        confidence=v.get("confidence"),
        triage_reasoning=reasoning,
        suggested_fix=v.get("suggested_fix"),
        severity=v.get("severity"),
        contract_class=v.get("contract_class"),
        gap_type=_split_gap_type(finding, v.get("gap_type")),
    )


def _apply_cached(finding: Finding, cached: dict) -> Finding:
    """Return a copy of ``finding`` with triage outputs from a cache entry."""

    return replace(
        finding,
        verdict=cached.get("verdict"),
        confidence=cached.get("confidence"),
        triage_reasoning=cached.get("triage_reasoning"),
        suggested_fix=cached.get("suggested_fix"),
        severity=cached.get("severity"),
        contract_class=cached.get("contract_class"),
        gap_type=_split_gap_type(finding, cached.get("gap_type")),
    )


def _render_evidence(ev: Evidence) -> str:
    """Render a single Evidence into the claim prompt (positional, not semantic)."""

    if ev.kind == "cross_file_reference":
        references = ev.payload.get("references", [])
        scope = ev.payload.get("scan_scope")
        out = []
        if references:
            out.append("Cross-file references:")
            for ref in references:
                resolves = " (resolves to source)" if ref.get("resolves_to_source") else ""
                same_file = " (same file, outside the flagged region)" if ref.get("same_file") else ""
                quoted = " [match is inside a quoted string]" if ref.get("in_string_literal") else ""
                line = f":{ref['line']}" if ref.get("line") else ""
                out.append(
                    f"- `{ref.get('file')}{line}` [{ref.get('kind')}]{same_file}{quoted}: "
                    f"{ref.get('context')}{resolves}"
                )
            if scope:
                totals = scope.get("needle_totals") or {}
                shown = {}
                for ref in references:
                    if ref.get("needle"):
                        shown[ref["needle"]] = shown.get(ref["needle"], 0) + 1
                per_needle = ", ".join(
                    f"`{needle}`: {total} match(es)"
                    + (f" ({shown[needle]} shown)" if shown.get(needle, total) < total else "")
                    for needle, total in totals.items()
                ) or ", ".join(scope.get("needles", []))
                out.append(
                    f"(reference sweep covered {scope.get('files_scanned')} files — "
                    f"{per_needle})"
                )
        elif scope:
            # Evidence-of-absence: state it explicitly — the canonical case-FOR
            # a reachability claim is the zero-hit sweep with honest scope.
            swept = (
                "including the flagged file outside the flagged region"
                if scope.get("same_file_swept")
                else "outside the flagged file"
            )
            out.append(
                f"No references found: {scope.get('files_scanned')} files swept "
                f"for {', '.join(scope.get('needles', []))} — zero matches, {swept}."
            )
            if scope.get("truncated"):
                out.append(
                    "CAUTION: the scan corpus was TRUNCATED at its size cap — "
                    "this zero is not evidence-of-absence for the whole repository."
                )
        surface = ev.payload.get("export_surface")
        if surface:
            exported = "IS" if surface.get("exported_from_flagged_file") else "is NOT"
            out.append(
                f"Export surface: `{surface.get('symbol')}` {exported} part of the "
                "flagged file's export list (exported symbols may have consumers "
                "outside this repository)."
            )
        for file, excerpt in (ev.payload.get("shadow_excerpts") or {}).items():
            out.append(f"Shadow doc for `{file}`:\n{excerpt}")
        if out:
            return "\n".join(out)
        return "Cross-file references: none gathered."
    if ev.kind == "surrounding_code":
        p = ev.payload
        out = [
            f"Surrounding code `{p.get('file')}` "
            f"L{p.get('line_start')}-{p.get('line_end')} (anchor: {p.get('anchor')}):"
        ]
        enclosing = p.get("enclosing_symbol")
        if enclosing:
            out.append(
                f"Enclosing {enclosing.get('kind')} `{enclosing.get('name')}` "
                f"(L{enclosing.get('line_start')}-{enclosing.get('line_end')})"
            )
        out.append(f"```\n{p.get('snippet', '')}\n```")
        return "\n".join(out)
    if ev.kind == "declared_intent":
        p = ev.payload
        out = [f"Declared intent near the flagged region of `{p.get('file')}`:"]
        for block in p.get("blocks", []):
            symbol = f" of `{block['symbol']}`" if block.get("symbol") else ""
            out.append(
                f"[{block.get('label')}{symbol}, from L{block.get('line_start')}]\n"
                f"{block.get('text', '')}"
            )
        return "\n".join(out)
    if ev.kind == "type_signature":
        p = ev.payload
        return f"Type `{p.get('type_name')}` defined in `{p.get('file')}`:\n```\n{p.get('source', '')}\n```"
    if ev.kind == "shadow_doc_claim":
        p = ev.payload
        scope = f" ({p['scope']} scope)" if p.get("scope") else ""
        body = p.get("excerpt") or p.get("content", "")
        return f"Shadow doc `{p.get('file')}`{scope}:\n{body}"
    return json.dumps(ev.payload, ensure_ascii=False, default=str)
