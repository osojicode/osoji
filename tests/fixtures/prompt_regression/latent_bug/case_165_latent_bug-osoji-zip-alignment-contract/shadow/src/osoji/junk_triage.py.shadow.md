# src\osoji\junk_triage.py
@source-hash: 218505d62e7affa6
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:43Z

## Purpose
Shared Triage driver for Phase-4 "junk" analyzers (V1-5). Provides two seam functions — `build_junk_claims` and `decide_junk_claims` — so all junk analyzers share a single claim-assembly and batched-decide pipeline instead of private `_verify_batch_async` LLM gates.

## Key Constants
- `BATCH_SIZE = 12` (L41): Max claims per `Triage.decide_batch` call; empirically measured limit under bounded payload caps for the claude-code provider.

## Key Functions

### `build_junk_claims` (L44-52)
Thin wrapper around `build_claims`. Converts a `Sequence[Finding]` + `BuildContext` into `list[Claim]`. Optional `schema` dict passed through. Single seam so analyzers don't import `claim_builder` directly.

**Parameters:** `findings: Sequence[Finding]`, `ctx: BuildContext`, `schema: dict | None = None`  
**Returns:** `list[Claim]`

### `decide_junk_claims` (L55-148)
Async batched Triage runner. Full pipeline:
1. **Short-circuit** (L70-71): returns `([], 0, 0)` immediately if no claims.
2. **VerdictSession** (L76): reads `config.verdict_session` via `getattr` (optional; injected by audit orchestrator for caching and manifest rewrite).
3. **File-adjacency ordering** (L81-84): groups claim indices by `claim.finding.path` then flattens, keeping same-file claims together for better batch context.
4. **Chunking** (L85): slices ordered indices into `batch_size`-sized chunks.
5. **Triage instantiation** (L87): `Triage(config, provider=provider)` — provider injected, not owned.
6. **Concurrent dispatch** (L140): `gather_with_buffer` fans out `run_chunk` coroutines over all chunks.
7. **Inner `decide`** (L93-120): calls `triage.decide_batch` in `"claim"` mode. On failure with `allow_bisect=True` and >1 index, bisects chunk and retries halves with `allow_bisect=False`. On terminal failure, stores the undecided original `Finding` (verdict=None) and prints an error. On success, accumulates token counts and stores `Finding` results.
8. **Inner `run_chunk`** (L122-138): calls `decide`, then under a lock increments `completed` and fires `on_progress(completed, total_chunks, first_claim_path, "{N} confirmed")`.
9. **Fallback** (L142-144): if any `results[i]` is still `None` (shouldn't happen after decide), substitutes `claims[i].finding`.
10. **Session harvest** (L146-147): calls `session.harvest(findings)` if session present.

**Parameters:**
- `claims: Sequence[Claim]`
- `config: Config`
- `provider: Any` — rate-limited logging provider; not closed by Triage
- `batch_size: int = BATCH_SIZE`
- `system_prompt: str = TRIAGE_SYSTEM_PROMPT`
- `on_progress: Callable[[int, int, Path, str], None] | None = None`

**Returns:** `tuple[list[Finding], int, int]` — `(findings, input_tokens, output_tokens)`, findings aligned 1:1 with input claims.

## Architecture & Patterns
- **Provider injection**: Triage does not own/close the provider; per-analyzer token accounting remains intact.
- **One bisect retry**: chunk failure bisects once (`allow_bisect=True` → `False`), then on second failure the undecided finding passthrough matches legacy dropped-batch behavior.
- **VerdictSession duck-typed**: accessed via `getattr(config, "verdict_session", None)` — no hard dependency; `session.cache` passed to `decide_batch`, `session.harvest()` called post-decide.
- **Lock on progress**: `asyncio.Lock` guards `completed` counter and `on_progress` callback to avoid concurrent mutation.
- **`gather_with_buffer`**: concurrency-bounded fan-out; lambda captures `idx` to avoid closure-over-loop-variable issue (L140).
