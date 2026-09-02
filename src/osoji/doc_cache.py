"""Doc-analysis result cache (osojicode/work#106).

``.osoji/doc-analysis-cache.json`` persists the large-tier ``analyze_document``
proposal for every doc the last audit analyzed, keyed on everything that
prompt is built from: the doc content as sent, the shadow docs actually sent
(after the per-doc char cap), the project rules, the large-tier model, and
osoji's ``impl_hash``. A later ``osoji audit --incremental`` serves a doc whose
key is unchanged without the LLM call. The served proposal still flows
through the Triage post-pass, where the verdict cache handles its findings —
so the cache captures the proposal *before* Triage mutates it.

Mirrors :mod:`osoji.audit_manifest`: the file lives directly under ``.osoji/``
(the audit wipes ``.osoji/analysis/`` at the start of every run), the
``osoji_version`` stamp is a coarse fast-path on top of the per-entry key,
reading is opt-in (``--incremental``/``--since``, never under ``--force``) and
writing is unconditional whenever doc analysis ran. The file is rewritten
wholesale from this run's docs, so docs that vanished drop out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .hasher import compute_children_hash, compute_hash, compute_impl_hash

if TYPE_CHECKING:
    from .doc_analysis import DocAnalysisResult

#: Cache file format version; bump on breaking shape changes.
DOC_CACHE_SCHEMA = 1


def doc_cache_key(
    *,
    doc_content: str,
    shadow_contexts: list[tuple[Path, str]],
    rules_text: str,
    model: str,
    impl_hash: str | None = None,
) -> str:
    """Hash every input the large-tier prompt is built from.

    The shadow set is hashed Merkle-style over ``(path, content_hash)`` pairs,
    so order does not matter but an added, removed or regenerated shadow does.
    ``impl_hash`` defaults to the live value; tests pin it.
    """

    if impl_hash is None:
        impl_hash = compute_impl_hash()
    shadow_hash = compute_children_hash([
        (str(path).replace("\\", "/"), compute_hash(content))
        for path, content in shadow_contexts
    ])
    return compute_hash("\n".join([
        f"doc-cache/{DOC_CACHE_SCHEMA}",
        impl_hash,
        model,
        compute_hash(rules_text or ""),
        compute_hash(doc_content),
        shadow_hash,
    ]))


def load_doc_cache(path: Path) -> dict | None:
    """Load and validate the cache file; None on missing/corrupt/unknown shape."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != DOC_CACHE_SCHEMA:
        return None
    if not isinstance(data.get("entries"), dict):
        return None
    return data


def write_doc_cache(
    path: Path,
    entries: dict[str, dict],
    *,
    commit: str | None,
    version: str,
) -> None:
    """Write the cache atomically (temp file + rename)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": DOC_CACHE_SCHEMA,
        "audited_commit": commit,
        "osoji_version": version,
        "entries": entries,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass
class DocCacheSession:
    """Per-audit-run doc-cache state, consulted by ``analyze_docs_async``.

    ``previous`` is the loaded file's entries (empty unless reading is
    enabled and the file's stamp matched); ``current`` accumulates this run's
    entries — cache hits carried forward plus fresh proposals — and is what
    the orchestrator writes back. ``get`` counts a lookup only when reading
    is enabled, so ``hit_rate`` is None on a run that never consulted the
    cache rather than a misleading 0.0.
    """

    previous: dict[str, dict] = field(default_factory=dict)
    current: dict[str, dict] = field(default_factory=dict)
    read_enabled: bool = False
    lookups: int = 0
    hits: int = 0

    def get(self, rel_path: str, key: str) -> DocAnalysisResult | None:
        if not self.read_enabled:
            return None
        self.lookups += 1
        entry = self.previous.get(rel_path)
        if not isinstance(entry, dict) or entry.get("key") != key:
            return None
        from .doc_analysis import DocAnalysisResult  # local: doc_analysis imports this module

        try:
            result = DocAnalysisResult.from_dict(entry["result"])
        except (KeyError, TypeError, ValueError):
            return None  # corrupt entry: a miss, never a crash
        self.hits += 1
        self.current[rel_path] = {"key": key, "result": entry["result"]}
        return result

    def put(self, rel_path: str, key: str, result: DocAnalysisResult) -> None:
        # Snapshot now: the Triage post-pass rewrites result.findings in place.
        self.current[rel_path] = {"key": key, "result": result.to_dict()}

    @property
    def hit_rate(self) -> float | None:
        if self.lookups == 0:
            return None
        return self.hits / self.lookups
