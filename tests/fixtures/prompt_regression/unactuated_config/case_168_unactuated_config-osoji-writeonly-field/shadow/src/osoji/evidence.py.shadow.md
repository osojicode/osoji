# src\osoji\evidence.py
@source-hash: 13fc11efe998435c
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:04Z

## Purpose
Defines the `Evidence` dataclass and the closed `EvidenceKind` taxonomy for the osoji Finding/Triage architecture (v1). Acts as the schema layer for typed evidence pieces assembled before Triage runs. Intentionally import-light to avoid circular imports with `findings.py`.

## Key Symbols

### `EvidenceKind` (L37–46) — `Literal` type alias
Closed set of 8 evidence kind discriminants:
- `"ast_fact"`, `"cross_file_reference"`, `"shadow_doc_claim"`, `"scanner_metadata"`, `"git_blame"`, `"type_signature"`, `"surrounding_code"`, `"declared_intent"`

No `"other"` outlet by design — all kinds are producer-controlled, not classified from external input.

### `EVIDENCE_KINDS` (L48–57) — `tuple[EvidenceKind, ...]`
Runtime-accessible tuple mirror of `EvidenceKind`. Used for iteration/membership checks where the `Literal` type isn't sufficient.

### `Evidence` (L60–96) — frozen dataclass
Core data container. Fields:
- `kind: EvidenceKind` — discriminant (L75)
- `weight_hint: float = 0.0` — producer's prior on evidence load-bearing weight, range `[0, 1]`; `0.0` = no prior (L76)
- `payload: dict[str, Any] = field(default_factory=dict)` — kind-specific free-form structure (L77)

Methods:
- `to_dict()` (L79–86): Returns JSON-serializable `{"kind", "weight_hint", "payload"}` dict
- `from_dict(data)` (L88–96): Classmethod reconstructor; uses `.get()` with defaults for `weight_hint` and `payload`, handles `None` payload via `or {}`

### `EvidenceBuilder` (L108–127) — ABC
Contract for builder plugins. Class attribute `kind: EvidenceKind` identifies what it produces. Abstract method `build(finding, ctx) -> list[Evidence]` must return evidence or `[]` — builders must never raise.

### `BUILDERS` (L132) — `dict[EvidenceKind, EvidenceBuilder]`
Empty registry dict. Populated at import time by `osoji.evidence_builders` (V1-4, not yet implemented). Used by Claim Builder to dispatch by kind.

## Architecture / Design Notes
- **Circular import prevention**: `findings.py` imports `Evidence` from this module; back-import of `Finding` is deferred to `TYPE_CHECKING` only (L24–26).
- **Schema evolution**: `payload` is a free-form dict intentionally — no migration needed when builder payloads change.
- **Adding a new kind** requires a `claim_builder.CLAIM_BUILDER_SCHEMA_VERSION` bump per the module docstring.
- `weight_hint` is flagged as a v2 removal candidate if LLM implicitly weights evidence.
- `BUILDERS` registry enables declarative Claim Builder configuration (list of kinds to invoke) vs. hardcoded logic.

## Dependencies
- `osoji.evidence_builders.BuildContext` — TYPE_CHECKING only (L25)
- `osoji.findings.Finding` — TYPE_CHECKING only (L26)
- No runtime cross-module imports from this project