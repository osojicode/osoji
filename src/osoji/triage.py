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
TRIAGE_SYSTEM_PROMPT = """\
You are osoji's Triage stage: the single verifier for every code-quality finding.

Every finding is a hypothesis about a GAP between what the code claims and what it does:
- reachability — declared/claimed to be used, but actually unreachable
  (dead code, dead parameters, unactuated config, orphaned files, unused deps).
- description — described one way (comment, docstring, name, type), behaves another
  (stale comments, misleading docstrings, latent bugs that violate a stated contract).
- contract — an implicit cross-component agreement (shared string, schema, ABI) is broken
  (obligation violations, cross-file string drift).
- uncategorized — does not fit cleanly; decide on the merits and say so.

A finding is a TRUE POSITIVE iff both predicates hold:
- Reality — the gap actually exists in the code, NOW (the evidence supports it).
  Code that matches its own documented, intended design is not a gap — an
  intent-documented behavior fails Reality, however improvable it may be. So does a
  not-yet-real observation: future fragility or robustness advice about code that
  currently behaves correctly describes a gap that does not exist yet.
- Actionability — there is a concrete fix.
Confirm when both hold. Dismiss when either fails. Use 'uncertain' when the
assembled evidence genuinely cannot decide.

Significance GRADES a confirmed finding; it never gates one. Set severity by how much
closing the gap improves the codebase: 'error' when the gap corrupts behavior or
misleads (silent contract breaks, docs that state falsehoods), 'warning' for the
typical real gap, 'info' when the gap is real and fixable but minor. Never dismiss a
real, actionable finding for being minor — it is not Triage's job to adjudicate
between correct findings; ordering work belongs to the consumer of the report.

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
                        [c for _, c in claim_route], system_prompt, provider
                    )
                    for (idx, _), fnd in zip(claim_route, decided):
                        findings[idx] = fnd
                    in_tok += ti
                    out_tok += to
                for idx, claim in explore_route:
                    fnd, ti, to, trace = await self._run_exploration(
                        claim, system_prompt, provider
                    )
                    findings[idx] = fnd
                    in_tok += ti
                    out_tok += to
                    traces.append(trace)
            finally:
                if owns:
                    await provider.close()

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
        self, claims: list[Claim], system_prompt: str, provider: Any
    ) -> tuple[list[Finding], int, int]:
        n = len(claims)
        user = self._render_claim_batch(claims)

        def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
            if tool_name != "submit_triage_verdicts":
                return []
            by_index = {
                v.get("batch_index"): v for v in tool_input.get("verdicts", [])
            }
            errors = [
                f"Missing verdict for batch_index {i}" for i in range(n) if i not in by_index
            ]
            # Symbol echo guard: sibling claims (two params of one function)
            # are easy to cross-wire by index alone — a mismatched echo means
            # the verdict was written about a different claim.
            for i, claim in enumerate(claims):
                echoed = (by_index.get(i) or {}).get("symbol")
                expected = claim.finding.symbol
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
                for v in tc.input.get("verdicts", []):
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
        if finding.symbol:
            lines.append(f"Symbol: `{finding.symbol}`")
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
        self, claim: Claim, system_prompt: str, provider: Any
    ) -> tuple[Finding, int, int, dict[str, Any]]:
        """Decide one claim via a multi-turn read/grep/list loop.

        The model is given the claim plus read-only retrieval tools and a terminal
        ``submit_triage_verdict`` tool. Every tool call is recorded to the trace
        (for V1-4 mining). Reaching the turn limit without a verdict yields
        ``uncertain``. Tool results are fed back as Anthropic content blocks — the
        provider passes ``Message.content`` straight through (see
        ``llm/anthropic.py``), so assistant ``tool_use`` and user ``tool_result``
        blocks round-trip without a dedicated message role.
        """

        finding = claim.finding
        user = (
            self._render_claim_block(0, finding)
            + "\nExplore the repository with read_file / grep / list_dir as needed, "
            "then call submit_triage_verdict with your decision."
        )
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


def _apply_verdict(finding: Finding, v: dict) -> Finding:
    """Return a copy of ``finding`` with triage outputs from a verdict dict."""

    return replace(
        finding,
        verdict=v.get("verdict"),
        confidence=v.get("confidence"),
        triage_reasoning=v.get("reasoning"),
        suggested_fix=v.get("suggested_fix"),
        severity=v.get("severity"),
        contract_class=v.get("contract_class"),
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
