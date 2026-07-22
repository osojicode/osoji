# src\osoji\findings.py
@source-hash: a3167f90bcba3d3e
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:34Z

## Purpose
Defines the canonical `Finding` dataclass for the osoji v1 architecture — a frozen, hashable schema representing a single code-quality "gap hypothesis" produced by a detector, with triage fields filled later by the Triage stage.

## Key Types

### `GapType` (L31)
`Literal["reachability", "description", "contract", "uncategorized"]` — closed taxonomy from three-gap theory. The `uncategorized` valve tracks taxonomy adequacy (CE-gap rate).

### `Verdict` (L34)
`Literal["confirmed", "dismissed", "uncertain"]` — triage output, `None` until Triage stage runs.

### `Severity` (L35)
`Literal["error", "warning", "info"]` — triage output, `None` until Triage stage runs.

## Key Functions

### `compute_finding_id` (L38–68)
Computes a stable content-addressed hash identifying a finding. Identity key: `(detector, path, symbol, contract_claim)`. Line numbers are **excluded** when `symbol` is present (stable anchor avoids cache-busting on cosmetic edits). When `symbol is None`, `(line_start, line_end)` are appended as fallback. Uses `json.dumps` (not delimiter join) to prevent injection/collision via embedded separator characters. Calls `compute_hash` from `.hasher`.

## Main Class

### `Finding` (L71–161) — `@dataclass(frozen=True)`
Immutable schema for a single gap hypothesis. Fields:

**Required (identity/claim):**
- `detector: str` — uniform `"<producer>:<category>"` format (L81)
- `gap_type: GapType` (L82)
- `path: str` (L83)
- `line_start: int | None`, `line_end: int | None` (L84–85)
- `symbol: str | None` (L86)
- `contract_source: str` — what states the claim (e.g. `"docstring"`) (L87)
- `contract_claim: str` — what the code/doc states (L88)
- `observed_behavior: str` — what actually happens (L89)

**Defaulted:**
- `evidence: list[Evidence]` — pre-triage support, default empty list (L92)
- `id: str` — computed in `__post_init__` if empty; preserved verbatim if non-empty (L93)

**Triage outputs (all `None` at propose time, filled by V1-3):**
- `verdict: Verdict | None` (L96)
- `confidence: float | None` (L97)
- `triage_reasoning: str | None` (L98)
- `suggested_fix: str | None` (L99)
- `severity: Severity | None` (L100)

**Contract-gap extension (V1-5c):**
- `contract_class: str | None` — taxonomy class assigned by Triage; `None` for all non-contract detectors (L106)

**Incremental-audit hook (V1-9):**
- `evidence_fingerprint: str | None` — filled by Claim Builder in V1-4; excluded from `id` (L111)

### `__post_init__` (L113–126)
Uses `object.__setattr__` to set `id` on the frozen dataclass when it is empty. Delegates to `compute_finding_id`.

### `to_dict` (L128–131)
Returns `asdict(self)` — fully JSON-serializable; `Evidence` fields recurse via `dataclasses.asdict`.

### `from_dict` (L133–161)
Class method. Reconstructs a `Finding` from a raw dict, rebuilding nested `Evidence` objects via `Evidence.from_dict`. Preserves stored `id` verbatim (non-empty) to keep corpus fixture round-trips stable. Required fields accessed with `data["key"]`; optional fields use `data.get(...)`.

## Naming / Architecture Note
`src/osoji/shadow.py` defines a **different legacy** `Finding` class (per-file debris shape). These are distinct; new code must `from osoji.findings import Finding`. Reconciliation planned for V1-5.

## Dependencies
- `.evidence.Evidence` — nested evidence schema
- `.hasher.compute_hash` — stable content hash primitive
- `dataclasses.asdict` — serialization
- `json.dumps` — collision-safe serialization of hash parts