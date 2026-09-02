"""Unit tests for the doc-analysis result cache (osojicode/work#106).

``analyze_document`` runs on the large tier for every doc every run and was
82 % of an incremental run's cost on mcp-debugger. The cache keys a doc's
proposed ``DocAnalysisResult`` on everything the large-tier prompt is built
from, so an unchanged doc against unchanged shadows is served without an LLM
call. These tests cover the key, the serialization round-trip, the on-disk
file and the per-run session; the audit-level wiring lives in
``test_audit_incremental.py``.
"""

import json
from pathlib import Path

from osoji.doc_analysis import DocAnalysisResult, DocFinding
from osoji.doc_cache import (
    DOC_CACHE_SCHEMA,
    DocCacheSession,
    doc_cache_key,
    load_doc_cache,
    write_doc_cache,
)


def _finding(**over) -> DocFinding:
    base = dict(
        category="stale_content",
        severity="error",
        description="says X, code does Y",
        shadow_ref="src/x.py",
        evidence="quote",
        remediation="fix the doc",
        search_terms=["foo", "bar"],
    )
    base.update(over)
    return DocFinding(**base)


def _result(**over) -> DocAnalysisResult:
    base = dict(
        path=Path("docs/a.md"),
        classification="reference",
        confidence=0.9,
        classification_reason="reads like a reference",
        matched_shadows=["src/x.py"],
        findings=[_finding()],
    )
    base.update(over)
    return DocAnalysisResult(**base)


_KEY = dict(
    doc_content="# A\n",
    shadow_contexts=[(Path("src/x.py"), "shadow of x")],
    rules_text="",
    model="claude-opus-4-6",
    impl_hash="impl0",
)


class TestKey:
    def test_same_inputs_same_key(self):
        assert doc_cache_key(**_KEY) == doc_cache_key(**_KEY)

    def test_doc_change_flips_key(self):
        assert doc_cache_key(**{**_KEY, "doc_content": "# A changed\n"}) != doc_cache_key(**_KEY)

    def test_shadow_content_change_flips_key(self):
        changed = [(Path("src/x.py"), "shadow of x, regenerated")]
        assert doc_cache_key(**{**_KEY, "shadow_contexts": changed}) != doc_cache_key(**_KEY)

    def test_shadow_set_change_flips_key(self):
        bigger = _KEY["shadow_contexts"] + [(Path("src/y.py"), "shadow of y")]
        assert doc_cache_key(**{**_KEY, "shadow_contexts": bigger}) != doc_cache_key(**_KEY)

    def test_shadow_order_does_not_matter(self):
        a = [(Path("src/x.py"), "sx"), (Path("src/y.py"), "sy")]
        b = list(reversed(a))
        assert doc_cache_key(**{**_KEY, "shadow_contexts": a}) == doc_cache_key(**{**_KEY, "shadow_contexts": b})

    def test_rules_change_flips_key(self):
        assert doc_cache_key(**{**_KEY, "rules_text": "never flag TODOs"}) != doc_cache_key(**_KEY)

    def test_model_change_flips_key(self):
        assert doc_cache_key(**{**_KEY, "model": "claude-sonnet-4-6"}) != doc_cache_key(**_KEY)

    def test_impl_hash_change_flips_key(self):
        assert doc_cache_key(**{**_KEY, "impl_hash": "impl1"}) != doc_cache_key(**_KEY)


class TestRoundTrip:
    def test_result_round_trips_including_search_terms(self):
        original = _result()
        restored = DocAnalysisResult.from_dict(original.to_dict())
        assert restored == original
        assert restored.findings[0].search_terms == ["foo", "bar"]

    def test_round_trip_survives_json(self):
        original = _result(topic_signature={"dirs": ["src"]})
        payload = json.loads(json.dumps(original.to_dict()))
        assert DocAnalysisResult.from_dict(payload) == original

    def test_path_is_serialized_with_forward_slashes(self):
        assert _result(path=Path("docs") / "sub" / "a.md").to_dict()["path"] == "docs/sub/a.md"

    def test_finding_triage_fields_default_to_none(self):
        restored = DocFinding.from_dict(_finding().to_dict())
        assert restored.verdict is None
        assert restored.finding_id is None
        assert restored.description_class is None


class TestFile:
    def test_load_missing_returns_none(self, temp_dir):
        assert load_doc_cache(temp_dir / "missing.json") is None

    def test_load_corrupt_returns_none(self, temp_dir):
        path = temp_dir / "cache.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_doc_cache(path) is None

    def test_load_wrong_schema_returns_none(self, temp_dir):
        path = temp_dir / "cache.json"
        path.write_text(json.dumps({"schema": DOC_CACHE_SCHEMA + 1, "entries": {}}), encoding="utf-8")
        assert load_doc_cache(path) is None

    def test_write_then_load_round_trips(self, temp_dir):
        path = temp_dir / ".osoji" / "doc-analysis-cache.json"
        entries = {"docs/a.md": {"key": "k1", "result": _result().to_dict()}}

        write_doc_cache(path, entries, commit="abc123", version="cb-5:impl0")
        loaded = load_doc_cache(path)

        assert loaded["schema"] == DOC_CACHE_SCHEMA
        assert loaded["osoji_version"] == "cb-5:impl0"
        assert loaded["audited_commit"] == "abc123"
        assert loaded["entries"] == entries
        assert not path.with_suffix(".json.tmp").exists()


class TestSession:
    def _session(self, **over) -> DocCacheSession:
        kwargs = dict(
            previous={"docs/a.md": {"key": "k1", "result": _result().to_dict()}},
            read_enabled=True,
        )
        kwargs.update(over)
        return DocCacheSession(**kwargs)

    def test_hit_returns_result_and_carries_entry_forward(self):
        session = self._session()

        hit = session.get("docs/a.md", "k1")

        assert hit == _result()
        assert session.lookups == 1
        assert session.hits == 1
        assert session.current["docs/a.md"]["key"] == "k1"

    def test_key_mismatch_misses(self):
        session = self._session()

        assert session.get("docs/a.md", "k2") is None
        assert (session.lookups, session.hits) == (1, 0)
        assert "docs/a.md" not in session.current

    def test_unknown_doc_misses(self):
        session = self._session()

        assert session.get("docs/b.md", "k1") is None
        assert (session.lookups, session.hits) == (1, 0)

    def test_read_disabled_never_looks_up(self):
        session = self._session(read_enabled=False)

        assert session.get("docs/a.md", "k1") is None
        assert (session.lookups, session.hits) == (0, 0)

    def test_put_stores_a_snapshot_not_a_reference(self):
        session = self._session(previous={})
        result = _result()

        session.put("docs/a.md", "k9", result)
        result.findings.clear()  # triage later rewrites findings in place

        assert len(session.current["docs/a.md"]["result"]["findings"]) == 1
        assert session.current["docs/a.md"]["key"] == "k9"

    def test_hit_rate(self):
        assert self._session().hit_rate is None
        session = self._session()
        session.get("docs/a.md", "k1")
        session.get("docs/a.md", "nope")
        assert session.hit_rate == 0.5
