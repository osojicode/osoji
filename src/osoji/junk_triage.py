"""Shared claim-mode Triage driver for the junk (Phase 4) analyzers (V1-5).

The V1-5 migrations replace each analyzer's private ``_verify_batch_async``
LLM gate with the unified pipeline: candidates become :class:`Finding`
hypotheses, the Claim Builder assembles self-sufficient claims, and
:class:`~osoji.triage.Triage` decides them under the unified rubric. This
module holds the two pieces every Phase-4 analyzer shares:

- :func:`build_junk_claims` — the Claim Builder pass (thin wrapper so the
  analyzers depend on one seam, and so callers can inspect built claims
  before routing — deadcode splits AST-proven claims off mechanically).
- :func:`decide_junk_claims` — the batched decide loop: same-file claims kept
  adjacent, chunks capped at :data:`BATCH_SIZE` (the V1-4 measured maximum
  per call under the bounded payload caps), chunks run concurrently, one
  bisect retry on chunk failure. A claim whose chunk ultimately fails keeps
  its undecided finding (``verdict=None``); the analyzer's confirmed-only
  mapping then drops it, matching the legacy dropped-batch behavior.

The provider is injected (audit Phase 4 already builds a rate-limited logging
provider per analyzer); ``Triage`` does not own or close it, so per-analyzer
token accounting keeps working unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .async_utils import gather_with_buffer
from .claim_builder import build_claims
from .config import Config
from .evidence_builders import BuildContext
from .findings import Finding
from .llm.errors import classify_permanent_error
from .triage import TRIAGE_SYSTEM_PROMPT, Claim, Triage

#: Max claims per Triage call. V1-4 measured 12 claims/call as reliable on the
#: claude-code provider once per-claim payloads were capped; the binding
#: constraint was payload size, not claim count.
BATCH_SIZE = 12


def build_junk_claims(
    findings: Sequence[Finding],
    ctx: BuildContext,
    *,
    schema: dict | None = None,
) -> list[Claim]:
    """Assemble self-sufficient claims for junk-analyzer findings."""

    return build_claims(list(findings), ctx, schema=schema)


async def decide_junk_claims(
    claims: Sequence[Claim],
    config: Config,
    provider: Any,
    *,
    batch_size: int = BATCH_SIZE,
    system_prompt: str = TRIAGE_SYSTEM_PROMPT,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> tuple[list[Finding], int, int]:
    """Decide claims through Triage in bounded concurrent chunks.

    Returns ``(findings, input_tokens, output_tokens)`` with ``findings``
    aligned 1:1 with ``claims``.
    """

    if not claims:
        return [], 0, 0

    # V1-9: the audit orchestrator may attach a VerdictSession to config; its
    # cache short-circuits Triage for unchanged findings and its harvest
    # collects decided verdicts for the audit-manifest rewrite.
    session = getattr(config, "verdict_session", None)
    # #160: the orchestrator may attach a shared circuit breaker. Once a
    # permanent (billing/auth) error trips it, remaining chunks short-circuit
    # (kept undecided) instead of issuing calls that will fail identically.
    breaker = getattr(config, "provider_circuit_breaker", None)

    # Keep same-file claims adjacent (shared context reads batch better), then
    # pack greedily into bounded chunks; chunks may span files — claims are
    # self-sufficient by construction.
    by_path: dict[str, list[int]] = {}
    for i, claim in enumerate(claims):
        by_path.setdefault(claim.finding.path, []).append(i)
    ordered = [i for indices in by_path.values() for i in indices]
    chunks = [ordered[i: i + batch_size] for i in range(0, len(ordered), batch_size)]

    triage = Triage(config, provider=provider)
    results: list[Finding | None] = [None] * len(claims)
    tokens = {"in": 0, "out": 0}
    completed = 0
    lock = asyncio.Lock()

    async def decide(indices: list[int], *, allow_bisect: bool = True) -> None:
        # Circuit already open: don't issue a doomed call; keep undecided.
        if breaker is not None and breaker.tripped:
            for i in indices:
                results[i] = claims[i].finding
            return
        chunk = [claims[i] for i in indices]
        try:
            batch = await triage.decide_batch(
                chunk,
                mode="claim",
                system_prompt=system_prompt,
                verdict_cache=session.cache if session is not None else None,
            )
        except Exception as exc:
            # A permanent (billing/auth) failure will recur on every retry:
            # trip the breaker and keep this chunk undecided without bisecting.
            permanent = classify_permanent_error(exc)
            if permanent is not None:
                if breaker is not None:
                    breaker.trip(permanent)
                for i in indices:
                    results[i] = claims[i].finding
                return
            if allow_bisect and len(indices) > 1:
                mid = len(indices) // 2
                await decide(indices[:mid], allow_bisect=False)
                await decide(indices[mid:], allow_bisect=False)
                return
            for i in indices:
                results[i] = claims[i].finding  # undecided: verdict stays None
            paths = sorted({claims[i].finding.path for i in indices})
            print(
                f"  [error] triage chunk failed ({len(indices)} claim(s), "
                f"{', '.join(paths)}): {exc}",
                flush=True,
            )
            return
        tokens["in"] += batch.input_tokens
        tokens["out"] += batch.output_tokens
        for i, finding in zip(indices, batch.findings):
            results[i] = finding

    async def run_chunk(indices: list[int]) -> None:
        nonlocal completed
        await decide(indices)
        async with lock:
            completed += 1
            if on_progress:
                confirmed = sum(
                    1
                    for i in indices
                    if results[i] is not None and results[i].verdict == "confirmed"
                )
                on_progress(
                    completed,
                    len(chunks),
                    Path(claims[indices[0]].finding.path),
                    f"{confirmed} confirmed",
                )

    await gather_with_buffer([lambda idx=idx: run_chunk(idx) for idx in chunks])

    findings = [
        result if result is not None else claims[i].finding
        for i, result in enumerate(results)
    ]
    if session is not None:
        session.harvest(findings)
    return findings, tokens["in"], tokens["out"]
