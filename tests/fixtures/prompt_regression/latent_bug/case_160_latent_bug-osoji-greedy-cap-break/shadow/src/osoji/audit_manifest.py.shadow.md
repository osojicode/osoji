# src\osoji\audit_manifest.py
@source-hash: 87d1c53c95fbe1dc
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:19Z

## Purpose
Manages the incremental-audit verdict manifest (`.osoji/audit-manifest.json`), enabling `osoji audit --incremental` to reuse prior Triage verdicts for findings with unchanged evidence fingerprints. Handles manifest I/O, version validation, cache construction, verdict merging, and per-run session state.

## Key Constants & Exceptions

- **`MANIFEST_SCHEMA = 1`** (L32): File format version; manifest is rejected if `schema` field doesn't match.
- **`IncrementalAuditError`** (L35–36): `RuntimeError` subclass raised on incremental-audit precondition failures (e.g., bad `--since` argument). No additional logic — pure sentinel exception.

## Key Functions

### `current_version()` (L39–42)
Returns the osoji logic version stamp as `"{CLAIM_BUILDER_SCHEMA_VERSION}:{compute_impl_hash()}"`. Used as a coarse fast-path staleness check in the manifest's `osoji_version` field.

### `get_head_commit(root: Path) -> str | None` (L45–60)
Shells out to `git -C <root> rev-parse HEAD` with a 10-second timeout. Returns the SHA string or `None` on OSError, timeout, non-zero exit, or empty output. Safe to call outside git repos.

### `load_manifest(path: Path) -> dict | None` (L63–76)
Reads and validates a manifest JSON file. Returns `None` on: missing/unreadable file, JSON parse error, non-dict root, wrong `schema` version, or missing/non-dict `verdicts` key. Returns raw `dict` on success.

### `write_manifest(path, verdicts, *, commit, version)` (L79–97)
Atomically writes manifest via temp file + `rename`. Creates parent directories as needed. Payload shape: `{schema, audited_commit, osoji_version, verdicts}`. Temp file uses `.json.tmp` suffix (L95–97).

### `cache_from_verdicts(verdicts: dict[str, dict]) -> dict[tuple[str, str], dict]` (L100–111)
Converts flat `{finding_id -> entry}` verdicts dict into a `{(finding_id, evidence_fingerprint) -> entry}` lookup cache. Entries lacking `evidence_fingerprint` are excluded (per decision 0014). This is the cache consulted by `Triage.decide_batch`.

### `_producer(detector: str) -> str` (L114–117)
Internal helper. Extracts the producer prefix from a colon-separated detector tag (e.g., `"deadcode:dead_symbol"` → `"deadcode"`).

### `merge_verdicts(previous, harvested, ran_producers)` (L120–139)
Merges new harvested verdicts over a previous manifest. Producer-scoped: entries from producers in `ran_producers` are replaced wholesale (removing vanished findings); entries from producers that did NOT run are preserved. Result is `previous` (filtered) + all of `harvested`.

## Key Class

### `VerdictSession` (L142–181)
Dataclass threading verdict cache state through the Triage pipeline for one audit run.

**Fields:**
- `cache: dict[tuple[str, str], dict]` (L151) — pre-built `(id, fingerprint)` lookup from prior manifest, consulted by `Triage.decide_batch`
- `harvested: dict[str, dict]` (L152) — findings recorded this run, keyed by `finding.id` (last-write-wins for duplicate ids)
- `claims_seen: int` (L153) — total findings processed
- `cache_hits: int` (L154) — findings matched in cache

**Methods:**
- `harvest(findings: Iterable[Finding])` (L156–173): Iterates findings, increments counters, counts cache hits by `(id, fingerprint)` lookup, and records findings with non-None `verdict` and `fingerprint` into `harvested`. Captures: `detector`, `evidence_fingerprint`, `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity`, `contract_class`.
- `hit_rate` property (L175–180): Returns `cache_hits / claims_seen` or `None` if no claims seen.

## Architectural Notes
- Manifest lives at `.osoji/audit-manifest.json`, NOT under `.osoji/analysis/` (which is wiped each run) — see module docstring L15–16.
- Duplicate finding ids collapse to one entry (last write wins) in `harvested` — safe because reuse still requires matching fingerprint (L12–13).
- Evidence fingerprint already embeds schema version + `impl_hash`, so logic changes auto-invalidate entries; `osoji_version` is a coarse fast-path on top (L7–9).
- Atomic write uses `.json.tmp` + `Path.replace()` to avoid partial writes (L95–97).

## Dependencies
- `claim_builder.CLAIM_BUILDER_SCHEMA_VERSION`: embedded in version stamp
- `findings.Finding`: source of harvested fields (verdict, fingerprint, detector, etc.)
- `hasher.compute_impl_hash`: contributes to `current_version()` stamp
