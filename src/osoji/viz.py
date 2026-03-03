"""Data pipeline, health scoring, and HTTP server for codebase visualization."""

import json
import webbrowser
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .config import Config
from .hasher import compute_file_hash, compute_impl_hash, extract_impl_hash, extract_source_hash
from .scorecard import merge_ranges
from .walker import discover_files, discover_directories

_VIZ_HTML_PATH = Path(__file__).parent / "viz.html"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_lines(path: Path) -> int:
    """Count lines in a file. Returns 0 on error."""
    try:
        return len(path.read_text(errors="ignore").splitlines())
    except OSError:
        return 0


def _safe_read_json(path: Path) -> dict | None:
    """Read and parse a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------

def _compute_file_health(node: dict) -> float | None:
    """Compute health score for a single file node (0.0–1.0).

    Returns None if the file has no shadow doc data at all (never processed).

    Penalties compound geometrically: each -0.2 penalty multiplies score by 0.8.
    Two penalties → 0.8 * 0.8 = 0.64, three → 0.512, etc.

    Penalty triggers (each -0.2):
    - No shadow doc
    - Shadow doc is stale
    - Each error finding
    - Each warning finding
    - Junk fraction (scaled: junk_frac * 0.2 per full fraction)
    """
    # No shadow doc and no findings → never processed, health unknown
    if (not node.get("has_shadow")
            and node.get("error_count", 0) == 0
            and node.get("warning_count", 0) == 0):
        return None

    PENALTY = 0.2
    factor = 1.0 - PENALTY  # 0.8

    score = 1.0

    if not node.get("has_shadow"):
        score *= factor

    if node.get("is_stale", False):
        score *= factor

    # Each finding is a separate penalty
    error_count = node.get("error_count", 0)
    warning_count = node.get("warning_count", 0)
    for _ in range(error_count):
        score *= factor
    for _ in range(warning_count):
        score *= factor

    # Junk fraction: continuous geometric penalty
    junk_frac = node.get("junk_fraction", 0.0)
    if junk_frac > 0:
        score *= (1.0 - PENALTY * junk_frac)

    return max(0.0, min(1.0, score))


def _compute_aggregate_health(file_nodes: list[dict]) -> float | None:
    """Weighted average of file health scores by line count.

    Skips files with None health (never processed).
    Returns None if no files contribute.
    """
    total_weight = 0
    weighted_sum = 0.0
    for node in file_nodes:
        health = node.get("health_score")
        if health is None:
            continue
        lines = node.get("lines", 0)
        total_weight += lines
        weighted_sum += lines * health
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Generic schema mapping
# ---------------------------------------------------------------------------

def _to_generic_node(raw: dict) -> dict:
    """Convert osoji-specific file data to generic renderer schema."""
    arcs = []

    # Compression arc: shows compression ratio (0% = full ring, 90% = 1/10 ring).
    # Neutral color, separate from health.
    token_stats = raw.get("token_stats")
    if token_stats and token_stats.get("source_tokens", 0) > 0:
        ratio = token_stats["shadow_tokens"] / token_stats["source_tokens"]
        ratio = max(0.0, min(1.0, ratio))
        arcs.append({"label": "Compression Ratio", "value": ratio, "color": "#7a8a9a"})

    junk_frac = raw.get("junk_fraction", 0.0)
    if junk_frac > 0:
        arcs.append({"label": "Junk", "value": junk_frac, "color": "#f6993f"})

    detail = {}
    if raw.get("purpose"):
        detail["Purpose"] = raw["purpose"]
    detail["Lines"] = str(raw.get("lines", 0))
    detail["Staleness"] = "\u26a0 Stale" if raw.get("is_stale") else "\u2713 Current"
    if raw.get("symbol_count") is not None:
        detail["Symbols"] = f"{raw['symbol_count']} ({raw.get('symbols_public', 0)} public)"
    if raw.get("findings_count"):
        detail["Findings"] = str(raw["findings_count"])
    if raw.get("topics"):
        detail["Topics"] = ", ".join(raw["topics"])

    preview = (raw.get("shadow_doc") or "")[:500] or None

    return {
        "name": raw["name"],
        "type": "file",
        "path": raw["path"],
        "size": raw.get("lines", 0),
        "health": raw.get("health_score"),
        "has_errors": raw.get("error_count", 0) > 0,
        "arcs": arcs,
        "badges": [raw["file_role"]] if raw.get("file_role") else [],
        "detail": detail,
        "preview": preview,
    }


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def assemble_viz_data(config: Config) -> dict:
    """Build the complete visualization payload from .osoji/ sidecars.

    Returns a dict matching the generic renderer schema: tree of nodes
    with data-driven arcs, badges, and detail fields.
    """
    files = discover_files(config)
    dirs = discover_directories(config, files)

    # Load token cache
    token_cache: dict[str, dict] = {}
    tc_data = _safe_read_json(config.token_cache_path)
    if tc_data and isinstance(tc_data, dict):
        token_cache = tc_data

    # Build raw file nodes keyed by relative path (forward slashes)
    raw_nodes: dict[str, dict] = {}

    for file_path in files:
        rel = file_path.relative_to(config.root_path)
        rel_str = str(rel).replace("\\", "/")
        lines = _count_lines(file_path)

        node: dict = {
            "name": file_path.name,
            "path": rel_str,
            "lines": lines,
            "has_shadow": False,
            "is_stale": False,
            "shadow_doc": None,
            "error_count": 0,
            "warning_count": 0,
            "findings_count": 0,
            "junk_fraction": 0.0,
            "symbol_count": None,
            "symbols_public": 0,
            "file_role": None,
            "purpose": None,
            "topics": None,
            "token_stats": None,
        }

        # Shadow doc
        shadow_path = config.shadow_path_for(file_path)
        if shadow_path.exists():
            try:
                shadow_content = shadow_path.read_text(encoding="utf-8")
                node["has_shadow"] = True
                node["shadow_doc"] = shadow_content

                # Staleness check
                stored_hash = extract_source_hash(shadow_content)
                if stored_hash is not None:
                    try:
                        current_hash = compute_file_hash(file_path)
                        if stored_hash != current_hash:
                            node["is_stale"] = True
                        else:
                            # Source matches — check impl hash
                            cached_impl = extract_impl_hash(shadow_content)
                            if cached_impl is None or cached_impl != compute_impl_hash():
                                node["is_stale"] = True
                    except OSError:
                        pass
            except OSError:
                pass

        # Findings
        findings_path = config.findings_path_for(file_path)
        findings_data = _safe_read_json(findings_path)
        if findings_data:
            findings_list = findings_data.get("findings", [])
            node["findings_count"] = len(findings_list)
            for f in findings_list:
                sev = f.get("severity", "warning")
                if sev == "error":
                    node["error_count"] += 1
                else:
                    node["warning_count"] += 1

            # Junk fraction from findings line ranges
            if findings_list and lines > 0:
                ranges = []
                for f in findings_list:
                    ls = f.get("line_start", 0)
                    le = f.get("line_end", ls)
                    if ls > 0 and le >= ls:
                        ranges.append((ls, le))
                if ranges:
                    merged = merge_ranges(ranges)
                    junk_lines = sum(end - start + 1 for start, end in merged)
                    node["junk_fraction"] = min(junk_lines / lines, 1.0)

        # Symbols
        symbols_path = config.symbols_path_for(file_path)
        symbols_data = _safe_read_json(symbols_path)
        if symbols_data:
            symbols_list = symbols_data.get("symbols", [])
            node["symbol_count"] = len(symbols_list)
            node["symbols_public"] = sum(
                1 for s in symbols_list if s.get("visibility") == "public"
            )
            node["file_role"] = symbols_data.get("file_role")

        # Signature
        sig_path = config.signatures_path_for(file_path)
        sig_data = _safe_read_json(sig_path)
        if sig_data:
            node["purpose"] = sig_data.get("purpose")
            node["topics"] = sig_data.get("topics")

        # Token stats
        if rel_str in token_cache:
            node["token_stats"] = token_cache[rel_str]

        # Health score
        node["health_score"] = _compute_file_health(node)

        raw_nodes[rel_str] = node

    # Build generic file nodes
    generic_nodes: dict[str, dict] = {}
    for rel_str, raw in raw_nodes.items():
        generic_nodes[rel_str] = _to_generic_node(raw)

    # Build directory nodes
    dir_nodes: dict[str, dict] = {}
    for dir_path in dirs:
        rel = dir_path.relative_to(config.root_path)
        rel_str = str(rel).replace("\\", "/")
        if rel_str == ".":
            rel_str = ""

        name = dir_path.name or config.root_path.name

        dir_node: dict = {
            "name": name,
            "type": "directory",
            "path": rel_str,
            "children": [],
            "preview": None,
        }

        # Load directory shadow doc for preview
        dir_shadow_path = config.shadow_path_for_dir(dir_path)
        if dir_shadow_path.exists():
            try:
                content = dir_shadow_path.read_text(encoding="utf-8")
                dir_node["preview"] = content[:500] or None
            except OSError:
                pass

        dir_nodes[rel_str] = dir_node

    # Link parents → children
    for rel_str, node in generic_nodes.items():
        parent_str = str(Path(rel_str).parent).replace("\\", "/")
        if parent_str == ".":
            parent_str = ""
        if parent_str in dir_nodes:
            dir_nodes[parent_str]["children"].append(node)

    for rel_str, node in dir_nodes.items():
        if rel_str == "":
            continue  # root has no parent
        parent_str = str(Path(rel_str).parent).replace("\\", "/")
        if parent_str == ".":
            parent_str = ""
        if parent_str in dir_nodes:
            dir_nodes[parent_str]["children"].append(node)

    # Sort children: directories first (alpha), then files (alpha)
    for node in dir_nodes.values():
        node["children"].sort(key=lambda c: (0 if c["type"] == "directory" else 1, c["name"]))

    # Aggregate stats
    file_count = len(generic_nodes)
    dir_count = len(dir_nodes)
    file_node_list = list(raw_nodes.values())
    aggregate_health = _compute_aggregate_health(file_node_list)

    # Compute aggregate compression
    total_source_tokens = 0
    total_shadow_tokens = 0
    for raw in raw_nodes.values():
        ts = raw.get("token_stats")
        if ts:
            total_source_tokens += ts.get("source_tokens", 0)
            total_shadow_tokens += ts.get("shadow_tokens", 0)

    compression_pct = None
    if total_source_tokens > 0:
        compression_pct = round((1.0 - total_shadow_tokens / total_source_tokens) * 100)

    # Headline metrics
    headline_metrics = [
        {
            "label": "Health",
            "value": str(round(aggregate_health * 100)) if aggregate_health is not None else "\u2014",
            "unit": "%" if aggregate_health is not None else "",
        },
        {"label": "Files", "value": str(file_count), "unit": ""},
    ]
    if compression_pct is not None:
        headline_metrics.append({"label": "Compression", "value": str(compression_pct), "unit": "%"})

    # Arc legend — from arcs actually present
    arc_labels_seen: dict[str, str] = {}
    for node in generic_nodes.values():
        for arc in node.get("arcs", []):
            arc_labels_seen[arc["label"]] = arc["color"]
    arc_legend = [{"label": label, "color": color} for label, color in arc_labels_seen.items()]

    # Load scorecard
    scorecard = _safe_read_json(config.scorecard_path)

    # Root tree
    tree = dir_nodes.get("", {
        "name": config.root_path.name,
        "type": "directory",
        "path": "",
        "children": [],
        "preview": None,
    })

    return {
        "project_name": config.root_path.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "aggregate_health": round(aggregate_health, 4) if aggregate_health is not None else None,
        "file_count": file_count,
        "dir_count": dir_count,
        "headline_metrics": headline_metrics,
        "arc_legend": arc_legend,
        "scorecard": scorecard,
        "tree": tree,
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def _load_html_template() -> str:
    """Load the viz.html template from disk."""
    return _VIZ_HTML_PATH.read_text(encoding="utf-8")


class VizHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler serving static HTML and JSON data."""

    def __init__(self, html_content: str, json_content: str, *args, **kwargs):
        self._html = html_content
        self._json = json_content
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._html.encode("utf-8"))
        elif self.path == "/api/data.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._json.encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass


def serve_viz(config: Config, port: int = 8765, open_browser: bool = True) -> None:
    """Assemble viz data, start HTTP server, and optionally open browser."""
    import click

    click.echo("Assembling visualization data...")
    data = assemble_viz_data(config)
    json_str = json.dumps(data, indent=2)

    html_str = _load_html_template()

    handler = partial(VizHandler, html_str, json_str)
    host = "127.0.0.1"

    try:
        server = HTTPServer((host, port), handler)
    except OSError as e:
        raise click.ClickException(f"Cannot start server on port {port}: {e}") from e

    url = f"http://{host}:{port}"
    click.echo(f"Serving visualization at {url}")
    click.echo("Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nServer stopped.")
    finally:
        server.server_close()
