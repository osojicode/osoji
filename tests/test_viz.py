"""Tests for viz data pipeline, health scoring, and server wiring."""

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from osoji.config import Config
from osoji.hasher import compute_hash
from osoji.viz import (
    _compute_file_health,
    _compute_aggregate_health,
    _to_generic_node,
    assemble_viz_data,
    VizHandler,
)
from osoji.walker import clear_repo_files_cache


# ---------------------------------------------------------------------------
# Helpers — create synthetic .osoji/ sidecars in tmp_path
# ---------------------------------------------------------------------------

def _write_source(root: Path, rel_path: str, content: str = "x = 1\n") -> Path:
    full = root / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def _write_shadow(root: Path, rel_path: str, content: str | None = None, *, source_hash: str | None = None) -> Path:
    shadow_dir = root / ".osoji" / "shadow"
    shadow_file = shadow_dir / (rel_path + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = f"# {rel_path}\n"
        if source_hash:
            content = f"# {rel_path}\n@source-hash: {source_hash}\n"
    shadow_file.write_text(content, encoding="utf-8")
    return shadow_file


def _write_dir_shadow(root: Path, dir_rel: str, content: str = "# Directory\nOverview.") -> Path:
    shadow_dir = root / ".osoji" / "shadow"
    if dir_rel == "" or dir_rel == ".":
        shadow_file = shadow_dir / "_root.shadow.md"
    else:
        shadow_file = shadow_dir / dir_rel / "_directory.shadow.md"
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    shadow_file.write_text(content, encoding="utf-8")
    return shadow_file


def _write_findings(root: Path, rel_path: str, findings: list[dict]) -> Path:
    findings_dir = root / ".osoji" / "findings"
    findings_file = findings_dir / (rel_path + ".findings.json")
    findings_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": rel_path,
        "source_hash": "abc123",
        "generated": "2026-01-01T00:00:00Z",
        "findings": findings,
    }
    findings_file.write_text(json.dumps(data), encoding="utf-8")
    return findings_file


def _write_symbols(root: Path, rel_path: str, symbols: list[dict], file_role: str | None = None) -> Path:
    symbols_dir = root / ".osoji" / "symbols"
    sidecar = symbols_dir / (rel_path + ".symbols.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": rel_path,
        "source_hash": "abc123",
        "generated": "2026-01-01T00:00:00Z",
        "symbols": symbols,
    }
    if file_role:
        data["file_role"] = file_role
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    return sidecar


def _write_signature(root: Path, rel_path: str, purpose: str = "Does things", topics: list[str] | None = None) -> Path:
    sig_dir = root / ".osoji" / "signatures"
    sig_file = sig_dir / (rel_path + ".signature.json")
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "path": rel_path,
        "kind": "source",
        "purpose": purpose,
        "topics": topics or ["topic1", "topic2"],
        "public_surface": [],
    }
    sig_file.write_text(json.dumps(data), encoding="utf-8")
    return sig_file


def _write_token_cache(root: Path, entries: dict) -> Path:
    tc_path = root / ".osoji" / "token-cache.json"
    tc_path.parent.mkdir(parents=True, exist_ok=True)
    tc_path.write_text(json.dumps(entries), encoding="utf-8")
    return tc_path


def _write_scorecard(root: Path, data: dict | None = None) -> Path:
    sc_path = root / ".osoji" / "analysis" / "scorecard.json"
    sc_path.parent.mkdir(parents=True, exist_ok=True)
    sc_path.write_text(json.dumps(data or {"coverage_pct": 50.0}), encoding="utf-8")
    return sc_path


def _make_config(root: Path) -> Config:
    return Config(root_path=root, respect_gitignore=False)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear walker cache between tests."""
    clear_repo_files_cache()
    yield
    clear_repo_files_cache()


# ===========================================================================
# Data pipeline tests
# ===========================================================================

class TestAssembleEmptyProject:
    def test_valid_structure_with_zero_counts(self, tmp_path):
        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        assert data["project_name"] == tmp_path.name
        assert data["file_count"] == 0
        assert data["dir_count"] >= 0
        assert data["aggregate_health"] is None
        assert data["tree"]["type"] == "directory"
        assert data["headline_metrics"][0]["label"] == "Health"
        assert data["headline_metrics"][0]["value"] == "\u2014"
        assert isinstance(data["arc_legend"], list)
        assert data["scorecard"] is None


class TestAssembleSingleFile:
    def test_one_file_with_shadow(self, tmp_path):
        content = "def hello():\n    pass\n"
        _write_source(tmp_path, "src/hello.py", content)
        source_hash = compute_hash(content)
        _write_shadow(tmp_path, "src/hello.py", source_hash=source_hash)

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        assert data["file_count"] == 1
        tree = data["tree"]
        # Navigate to file — tree root → src dir → hello.py
        src_dir = next(c for c in tree["children"] if c["name"] == "src")
        file_node = next(c for c in src_dir["children"] if c["name"] == "hello.py")
        assert file_node["type"] == "file"
        assert file_node["path"] == "src/hello.py"
        assert file_node["size"] == 2
        assert file_node["health"] > 0


class TestAssembleTreeStructure:
    def test_nested_dirs_correct_parent_child(self, tmp_path):
        _write_source(tmp_path, "a/b/deep.py", "x = 1\n")
        _write_source(tmp_path, "a/shallow.py", "y = 2\n")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        a_dir = next(c for c in tree["children"] if c["name"] == "a")
        assert a_dir["type"] == "directory"

        # a has child dir b and file shallow.py
        child_names = [c["name"] for c in a_dir["children"]]
        assert "b" in child_names
        assert "shallow.py" in child_names

        b_dir = next(c for c in a_dir["children"] if c["name"] == "b")
        assert any(c["name"] == "deep.py" for c in b_dir["children"])


class TestAssembleStalenessDetected:
    def test_mismatched_hash_shows_stale(self, tmp_path):
        _write_source(tmp_path, "main.py", "v1\n")
        _write_shadow(tmp_path, "main.py", source_hash="wrong_hash_value")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "main.py")
        assert file_node["detail"]["Staleness"] == "\u26a0 Stale"


class TestAssembleFindingsLoaded:
    def test_findings_count_and_junk_arc(self, tmp_path):
        # 10-line file
        _write_source(tmp_path, "bad.py", "\n".join(f"line{i}" for i in range(10)) + "\n")
        _write_findings(tmp_path, "bad.py", [
            {"category": "dead_code", "severity": "error", "line_start": 1, "line_end": 3,
             "name": "old_func", "reason": "unused"},
        ])

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "bad.py")
        assert file_node["detail"]["Findings"] == "1"
        # Junk arc should be present
        junk_arcs = [a for a in file_node["arcs"] if a["label"] == "Junk"]
        assert len(junk_arcs) == 1
        assert junk_arcs[0]["value"] > 0


class TestAssembleSymbolsLoaded:
    def test_symbol_count_in_detail(self, tmp_path):
        _write_source(tmp_path, "lib.py", "class Foo:\n    pass\ndef bar():\n    pass\n")
        _write_symbols(tmp_path, "lib.py", [
            {"name": "Foo", "kind": "class", "line_start": 1, "line_end": 2, "visibility": "public"},
            {"name": "bar", "kind": "function", "line_start": 3, "line_end": 4, "visibility": "public"},
        ], file_role="service")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "lib.py")
        assert "Symbols" in file_node["detail"]
        assert "2" in file_node["detail"]["Symbols"]
        assert "2 public" in file_node["detail"]["Symbols"]
        assert file_node["badges"] == ["service"]


class TestAssembleSignaturesLoaded:
    def test_topics_and_purpose_in_detail(self, tmp_path):
        _write_source(tmp_path, "hasher.py", "import hashlib\n")
        _write_signature(tmp_path, "hasher.py", purpose="Provides hashing", topics=["SHA-256", "content hashing"])

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "hasher.py")
        assert file_node["detail"]["Purpose"] == "Provides hashing"
        assert "SHA-256" in file_node["detail"]["Topics"]


class TestAssembleTokenCacheLoaded:
    def test_compression_ratio_arc_present(self, tmp_path):
        _write_source(tmp_path, "big.py", "x = 1\n" * 100)
        _write_token_cache(tmp_path, {
            "big.py": {"source_tokens": 1000, "shadow_tokens": 300},
        })

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "big.py")
        comp_arcs = [a for a in file_node["arcs"] if a["label"] == "Compression Ratio"]
        assert len(comp_arcs) == 1
        assert abs(comp_arcs[0]["value"] - 0.3) < 0.01  # 300/1000 = 0.3 ratio
        assert comp_arcs[0]["color"] == "#7a8a9a"  # neutral color


class TestAssembleMissingSidecar:
    def test_file_with_no_sidecars(self, tmp_path):
        _write_source(tmp_path, "bare.py", "pass\n")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "bare.py")
        assert file_node["arcs"] == []
        assert file_node["badges"] == []
        assert file_node["preview"] is None
        assert file_node["health"] is None  # never processed → null
        assert file_node["detail"]["Staleness"] == "\u2713 Current"


class TestAssembleScorecardMissing:
    def test_no_scorecard_no_crash(self, tmp_path):
        _write_source(tmp_path, "ok.py", "x = 1\n")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)
        assert data["scorecard"] is None


class TestChildrenSorted:
    def test_dirs_first_then_files_alphabetical(self, tmp_path):
        _write_source(tmp_path, "zebra.py", "z = 1\n")
        _write_source(tmp_path, "alpha.py", "a = 1\n")
        _write_source(tmp_path, "mydir/inner.py", "i = 1\n")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        child_names = [c["name"] for c in tree["children"]]
        # Directory first, then files alphabetically
        dir_idx = child_names.index("mydir")
        alpha_idx = child_names.index("alpha.py")
        zebra_idx = child_names.index("zebra.py")
        assert dir_idx < alpha_idx < zebra_idx


class TestArcsDataDriven:
    def test_arcs_match_expected_labels_values_colors(self, tmp_path):
        # File with both compression and junk data
        content = "\n".join(f"line{i}" for i in range(20)) + "\n"
        _write_source(tmp_path, "mixed.py", content)
        _write_token_cache(tmp_path, {
            "mixed.py": {"source_tokens": 500, "shadow_tokens": 150},
        })
        _write_findings(tmp_path, "mixed.py", [
            {"category": "dead_code", "severity": "error", "line_start": 1, "line_end": 4,
             "name": "old", "reason": "unused"},
        ])

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "mixed.py")
        arc_labels = {a["label"] for a in file_node["arcs"]}
        assert "Compression Ratio" in arc_labels
        assert "Junk" in arc_labels

        comp = next(a for a in file_node["arcs"] if a["label"] == "Compression Ratio")
        assert comp["color"] == "#7a8a9a"  # neutral
        assert abs(comp["value"] - 0.3) < 0.01  # 150/500 = 0.3 ratio

        junk = next(a for a in file_node["arcs"] if a["label"] == "Junk")
        assert junk["color"] == "#f6993f"
        assert junk["value"] > 0


class TestGenericSchemaNoOsojiConcepts:
    def test_node_keys_are_generic(self, tmp_path):
        _write_source(tmp_path, "clean.py", "x = 1\n")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        file_node = next(c for c in tree["children"] if c["name"] == "clean.py")

        allowed_keys = {"name", "type", "path", "size", "health", "has_errors", "arcs", "badges", "detail", "preview"}
        assert set(file_node.keys()) == allowed_keys


class TestDirectoryPreview:
    def test_dir_shadow_loaded_as_preview(self, tmp_path):
        _write_source(tmp_path, "pkg/mod.py", "x = 1\n")
        _write_dir_shadow(tmp_path, "pkg", content="# Package\nThis is the package overview.")

        config = _make_config(tmp_path)
        data = assemble_viz_data(config)

        tree = data["tree"]
        pkg_dir = next(c for c in tree["children"] if c["name"] == "pkg")
        assert pkg_dir["preview"] is not None
        assert "Package" in pkg_dir["preview"]


# ===========================================================================
# Health score tests
# ===========================================================================

class TestHealthPerfect:
    def test_all_good_returns_1(self):
        node = {"has_shadow": True, "is_stale": False, "error_count": 0, "warning_count": 0,
                "junk_fraction": 0.0, "token_stats": None}
        assert _compute_file_health(node) == 1.0


class TestHealthNullWhenNeverProcessed:
    def test_no_shadow_no_findings_returns_none(self):
        node = {"has_shadow": False, "is_stale": False, "error_count": 0, "warning_count": 0,
                "junk_fraction": 0.0, "token_stats": None}
        assert _compute_file_health(node) is None

    def test_no_shadow_but_findings_returns_score(self):
        """File with findings but no shadow → has been audited, return a score."""
        node = {"has_shadow": False, "is_stale": False, "error_count": 1, "warning_count": 0,
                "junk_fraction": 0.0, "token_stats": None}
        result = _compute_file_health(node)
        assert result is not None
        # no_shadow * error = 0.8 * 0.8 = 0.64
        assert abs(result - 0.64) < 0.01


class TestHealthStale:
    def test_stale_penalty(self):
        node = {"has_shadow": True, "is_stale": True, "error_count": 0, "warning_count": 0,
                "junk_fraction": 0.0, "token_stats": None}
        # Geometric: 1.0 * 0.8 = 0.8
        assert abs(_compute_file_health(node) - 0.80) < 0.01


class TestHealthFindings:
    def test_errors_and_warnings_compound_geometrically(self):
        node = {"has_shadow": True, "is_stale": False, "error_count": 2, "warning_count": 3,
                "junk_fraction": 0.0, "token_stats": None}
        # 5 findings: 0.8^5 = 0.32768
        expected = 0.8 ** 5
        assert abs(_compute_file_health(node) - expected) < 0.01


class TestHealthStalePlusFindings:
    def test_stale_and_findings_compound(self):
        node = {"has_shadow": True, "is_stale": True, "error_count": 2, "warning_count": 0,
                "junk_fraction": 0.0, "token_stats": None}
        # stale + 2 errors = 3 penalties: 0.8^3 = 0.512
        expected = 0.8 ** 3
        assert abs(_compute_file_health(node) - expected) < 0.01


class TestHealthJunk:
    def test_junk_fraction_penalty(self):
        node = {"has_shadow": True, "is_stale": False, "error_count": 0, "warning_count": 0,
                "junk_fraction": 0.5, "token_stats": None}
        # Continuous: 1.0 * (1 - 0.2 * 0.5) = 0.9
        expected = 1.0 * (1.0 - 0.2 * 0.5)
        assert abs(_compute_file_health(node) - expected) < 0.01


class TestHealthFloor:
    def test_many_penalties_approach_zero(self):
        node = {"has_shadow": True, "is_stale": True, "error_count": 20, "warning_count": 20,
                "junk_fraction": 1.0, "token_stats": None}
        result = _compute_file_health(node)
        # Geometric compounding: approaches but may not reach exactly 0
        assert result < 0.001


class TestHealthManyWarnings:
    def test_100_warnings_produces_low_score(self):
        """With geometric compounding, many warnings should noticeably reduce health."""
        node = {"has_shadow": True, "is_stale": False, "error_count": 0, "warning_count": 5,
                "junk_fraction": 0.0, "token_stats": None}
        # 0.8^5 = 0.32768
        expected = 0.8 ** 5
        assert abs(_compute_file_health(node) - expected) < 0.01


class TestAggregateWeighted:
    def test_weighted_by_line_count(self):
        nodes = [
            {"lines": 100, "health_score": 1.0},
            {"lines": 100, "health_score": 0.5},
        ]
        result = _compute_aggregate_health(nodes)
        assert abs(result - 0.75) < 0.01

    def test_no_lines_returns_none(self):
        nodes = [{"lines": 0, "health_score": 1.0}]
        assert _compute_aggregate_health(nodes) is None


# ===========================================================================
# Server wiring tests
# ===========================================================================

class TestHandler:
    """Test VizHandler responses using a real ephemeral server."""

    @pytest.fixture()
    def server_url(self):
        from functools import partial
        from http.server import HTTPServer

        html = "<html><body>Test</body></html>"
        json_data = '{"test": true}'
        handler = partial(VizHandler, html, json_data)
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        server.shutdown()

    def test_root_200_html(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/")
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        body = resp.read().decode()
        assert "<html>" in body

    def test_api_200_json(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/data.json")
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = json.loads(resp.read())
        assert data["test"] is True

    def test_404_other_paths(self, server_url):
        from urllib.error import HTTPError
        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(f"{server_url}/bogus")
        assert exc_info.value.code == 404
