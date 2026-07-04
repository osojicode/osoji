"""Tests for the mechanized evidence builders (V1-4, osojicode/work#27).

The builders mechanize the evidence kinds mined from the Phase B exploration
traces (tests/fixtures/bootstrap/mining/mining-report.md), ratified at
Checkpoint 1:

- cross_file_reference: FactsDB refs + repo-wide text scan with per-site
  context, honest scan scope (zero hits over a non-empty scope is
  evidence-of-absence, not missing evidence), export-surface facts.
- surrounding_code: flagged region snippet, symbol-anchored against line drift.
- declared_intent: positional text blocks (preceding lines + enclosing symbol
  head) — the LLM recognizes comment/doc syntax, the builder does not.
- shadow_doc_claim: file shadow excerpt (+ directory shadow for description gaps).
- type_signature: legacy latent-bug type-definition lookup.

Builders never raise; a builder that cannot gather returns []. Sufficiency is
the schema layer's concern (claim_builder.SchemaEntry), not the builder's.
"""

import pytest

from osoji.config import Config
from osoji.evidence import BUILDERS, EVIDENCE_KINDS
from osoji.evidence_builders import BuildContext
from osoji.findings import Finding


@pytest.fixture
def config(temp_dir):
    return Config(root_path=temp_dir, respect_gitignore=False)


class FakeFacts:
    """Stand-in FactsDB: cross_file_references + optional export surface."""

    def __init__(self, refs_by_symbol=None, exports_by_file=None, files=None):
        self._refs = refs_by_symbol or {}
        self._exports = exports_by_file or {}
        self._file_list = files if files is not None else list(self._exports)

    def cross_file_references(self, symbol, source_path):
        return self._refs.get(symbol, [])

    def exported_names(self, file_path):
        return self._exports.get(file_path.replace("\\", "/"), set())

    def all_files(self):
        return list(self._file_list)


def make_finding(**over):
    base = dict(
        detector="debris:dead_code",
        gap_type="reachability",
        path="src/x.py",
        line_start=10,
        line_end=12,
        symbol="old_helper",
        contract_source="symbol declaration",
        contract_claim="Symbol `old_helper` is declared but appears unused",
        observed_behavior="No callers or importers of `old_helper` were found",
    )
    base.update(over)
    return Finding(**base)


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- schema evolution (C2) --------------------------------------------------


def test_new_evidence_kinds_are_registered():
    assert "surrounding_code" in EVIDENCE_KINDS
    assert "declared_intent" in EVIDENCE_KINDS


def test_every_produced_kind_has_a_builder():
    for kind in (
        "cross_file_reference",
        "surrounding_code",
        "declared_intent",
        "shadow_doc_claim",
        "type_signature",
    ):
        assert kind in BUILDERS, f"no builder registered for {kind}"
        assert BUILDERS[kind].kind == kind


# --- cross_file_reference ---------------------------------------------------


def test_cross_file_reference_uses_facts_db(config):
    facts = FakeFacts({"old_helper": [
        {"file": "src/y.py", "kind": "import",
         "context": "from x import old_helper", "resolves_to_source": True},
    ]})
    ctx = BuildContext(config, facts_db=facts, symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(), ctx)
    assert len(evidence) == 1
    refs = evidence[0].payload["references"]
    assert refs[0]["file"] == "src/y.py"
    assert refs[0]["source"] == "facts"


def test_cross_file_reference_text_scan_when_facts_empty(config, temp_dir):
    write(temp_dir, "src/x.py", "def old_helper():\n    return 1\n")
    write(temp_dir, "src/y.py", "from x import old_helper\nold_helper()\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(), ctx)
    assert len(evidence) == 1
    scan_refs = [r for r in evidence[0].payload["references"] if r["source"] == "text_scan"]
    assert any(r["file"] == "src/y.py" for r in scan_refs)
    assert any("old_helper" in r["context"] for r in scan_refs)


def test_text_scan_sweeps_beyond_flagged_file_pair(config, temp_dir):
    # The one true exploration miss: deciding evidence lived in a third file.
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    write(temp_dir, "src/y.py", "import x\n")
    write(temp_dir, "src/z.py", "handler = getattr(mod, 'old_helper')\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(), ctx)
    files = {r["file"] for r in evidence[0].payload["references"]}
    assert "src/z.py" in files


def test_text_scan_reports_same_file_usage_outside_flagged_region(config, temp_dir):
    # The wrapper-pattern FP class (ablation r1 lesson): the genuine usage of a
    # "dead" symbol often lives further down the SAME file. Those hits are
    # reported, tagged same_file; hits inside the flagged region (the
    # declaration itself) are not references and stay excluded.
    lines = ["def old_helper():", "    pass"] + ["# filler"] * 20 + [
        "def wrapper():", "    return old_helper()"]
    write(temp_dir, "src/x.py", "\n".join(lines) + "\n")
    write(temp_dir, "src/y.py", "print('unrelated')\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(line_start=1, line_end=2), ctx)
    refs = evidence[0].payload["references"]
    same_file = [r for r in refs if r.get("same_file")]
    assert same_file, "same-file usage outside the flagged region must be reported"
    assert all(r["line"] > 2 for r in same_file)  # declaration lines excluded


def test_symbolless_finding_uses_quoted_literals_as_needles(config, temp_dir):
    # Obligation findings carry symbol=None and quote the contract literal in
    # prose; the literal must become a scan needle regardless of gap_type
    # (ablation r1: needles were prose words like 'Implicit').
    write(temp_dir, "src/producer.py", "result['extraction_method'] = 'ast'\n")
    write(temp_dir, "src/consumer.py", "if method == 'ast':\n    pass\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        detector="obligations:obligation_implicit_contract",
        gap_type="uncategorized",  # the V1-2 adapter default, NOT "contract"
        path="src/producer.py",
        symbol=None,
        contract_claim="Implicit contract: literal 'ast' produced here",
        observed_behavior="String checked in src/consumer.py with no shared constant",
    )
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    needles = evidence[0].payload["scan_scope"]["needles"]
    assert "ast" in needles
    assert "Implicit" not in needles
    files = {r["file"] for r in evidence[0].payload["references"]}
    assert "src/consumer.py" in files


def test_zero_hit_scan_is_evidence_of_absence_with_scope(config, temp_dir):
    # Ratified at Checkpoint 1: zero hits across a NON-EMPTY scope is the
    # canonical case-FOR a reachability claim, carried with honest scope.
    # The declaration sits inside the flagged region, so the same-file sweep
    # (which excludes that region) finds nothing either.
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    write(temp_dir, "src/y.py", "print('nothing relevant')\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(
        make_finding(line_start=1, line_end=2), ctx
    )
    assert len(evidence) == 1
    payload = evidence[0].payload
    assert payload["references"] == []
    assert payload["scan_scope"]["files_scanned"] >= 1
    assert "old_helper" in payload["scan_scope"]["needles"]


def test_empty_scope_yields_no_evidence(config):
    # Nothing to scan and no facts: "we could not even look" — this is the
    # insufficient_evidence case, distinct from evidence-of-absence.
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(), ctx)
    assert evidence == []


def test_export_surface_reported_when_facts_know_the_file(config):
    facts = FakeFacts(
        exports_by_file={"src/x.py": {"old_helper", "other"}},
        files=["src/x.py", "src/y.py"],
    )
    ctx = BuildContext(config, facts_db=facts, symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(make_finding(), ctx)
    assert len(evidence) == 1
    surface = evidence[0].payload["export_surface"]
    assert surface["symbol"] == "old_helper"
    assert surface["exported_from_flagged_file"] is True


def test_literal_needles_use_word_boundaries(config, temp_dir):
    # Ablation r2 lesson: 'ast' must not match 'fastest' / 'last'.
    write(temp_dir, "src/producer.py", "method = 'ast'\n")
    write(temp_dir, "src/noise.py", "speed = 'fastest'\nlast = 1\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        path="src/producer.py", symbol=None, gap_type="uncategorized",
        contract_claim="Implicit contract: 'ast' produced here",
        observed_behavior="checked elsewhere",
    )
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    files = {r["file"] for r in evidence[0].payload["references"]}
    assert "src/noise.py" not in files


def test_claim_named_files_are_scanned_first(config, temp_dir):
    # Ablation r2 lesson: the hit cap must not starve the files the claim
    # names in prose — for contract findings those ARE the file tuple.
    for i in range(30):
        write(temp_dir, f"docs/aaa_{i:02}.md", "the shared_key appears here\n")
    write(temp_dir, "src/consumer.py", "value = conf['shared_key']\n")
    write(temp_dir, "src/producer.py", "conf = {'shared_key': 1}\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        path="src/producer.py", symbol=None, gap_type="uncategorized",
        contract_claim="Implicit contract: 'shared_key' produced in src/producer.py",
        observed_behavior="checked in src/consumer.py with no shared constant",
    )
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    files = {r["file"] for r in evidence[0].payload["references"]}
    assert "src/consumer.py" in files


def test_scan_scope_reports_per_needle_totals(config, temp_dir):
    for i in range(30):
        write(temp_dir, f"docs/n_{i:02}.md", "needle_word here\n")
    write(temp_dir, "src/x.py", "def needle_word():\n    pass\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(
        make_finding(symbol="needle_word", line_start=1, line_end=2), ctx
    )
    payload = evidence[0].payload
    totals = payload["scan_scope"]["needle_totals"]
    assert totals["needle_word"] == 30
    assert len([r for r in payload["references"] if r["needle"] == "needle_word"]) < 30


def test_scan_context_lines_are_length_capped(config, temp_dir):
    # Ablation r3 lesson: a hit inside a huge one-liner (lock files, JSON)
    # must not import the whole line into the claim payload.
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    write(temp_dir, "data/blob.txt", "x" * 50_000 + " old_helper " + "y" * 50_000 + "\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(
        make_finding(line_start=1, line_end=2), ctx
    )
    for ref in evidence[0].payload["references"]:
        assert len(ref["context"]) < 2_000


def test_scan_hits_are_capped_per_file_for_diversity(config, temp_dir):
    # Ablation r3 lesson: one noisy file must not fill the hit budget and
    # drown the diverse reference sites exploration actually consulted.
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    write(temp_dir, "src/noisy.py", "old_helper()\n" * 30)
    write(temp_dir, "src/other.py", "from x import old_helper\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(
        make_finding(line_start=1, line_end=2), ctx
    )
    refs = evidence[0].payload["references"]
    assert sum(1 for r in refs if r["file"] == "src/noisy.py") <= 3
    assert any(r["file"] == "src/other.py" for r in refs)


# --- surrounding_code -------------------------------------------------------


def test_surrounding_code_extracts_flagged_region(config, temp_dir):
    lines = [f"line {i}" for i in range(1, 31)]
    lines[9] = "def old_helper():"
    write(temp_dir, "src/x.py", "\n".join(lines) + "\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["surrounding_code"].build(make_finding(), ctx)
    assert len(evidence) == 1
    payload = evidence[0].payload
    assert payload["file"] == "src/x.py"
    assert "def old_helper():" in payload["snippet"]
    assert "10:" in payload["snippet"]  # numbered lines


def test_surrounding_code_symbol_anchor_survives_line_drift(config, temp_dir):
    # Audit entries carry line numbers from an older commit; the symbols DB
    # anchor wins over a drifted line_start.
    content = "\n".join(
        ["def old_helper():", "    return 42", ""] + [f"# filler {i}" for i in range(60)]
    )
    write(temp_dir, "src/x.py", content + "\n")
    symbols = {"src/x.py": [
        {"name": "old_helper", "kind": "function", "line_start": 1, "line_end": 2},
    ]}
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file=symbols)
    evidence = BUILDERS["surrounding_code"].build(make_finding(line_start=50, line_end=50), ctx)
    payload = evidence[0].payload
    assert "def old_helper():" in payload["snippet"]
    assert payload["anchor"] == "symbol"


def test_surrounding_code_missing_file_returns_empty(config):
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    assert BUILDERS["surrounding_code"].build(make_finding(), ctx) == []


# --- declared_intent --------------------------------------------------------


def test_declared_intent_captures_preceding_block_and_enclosing_head(config, temp_dir):
    content = "\n".join(
        [
            "def outer():",
            '    """Docstring stating intent."""',
            "    setup()",
            "    # NOTE: legacy compatibility shim",
            "    # kept until v2",
            "    old_helper()",
            "",
        ]
    )
    write(temp_dir, "src/x.py", content)
    symbols = {"src/x.py": [
        {"name": "outer", "kind": "function", "line_start": 1, "line_end": 6},
    ]}
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file=symbols)
    evidence = BUILDERS["declared_intent"].build(
        make_finding(line_start=6, line_end=6), ctx
    )
    assert len(evidence) == 1
    blocks = evidence[0].payload["blocks"]
    labels = {b["label"] for b in blocks}
    assert {"preceding_lines", "enclosing_head"} <= labels
    joined = "\n".join(b["text"] for b in blocks)
    assert "NOTE: legacy compatibility shim" in joined
    assert "Docstring stating intent" in joined


def test_declared_intent_missing_file_returns_empty(config):
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    assert BUILDERS["declared_intent"].build(make_finding(), ctx) == []


# --- shadow_doc_claim -------------------------------------------------------


def test_shadow_doc_builder_degrades_to_empty_without_shadow(config):
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    assert BUILDERS["shadow_doc_claim"].build(make_finding(), ctx) == []


def test_shadow_doc_builder_reads_file_shadow(config, temp_dir):
    write(temp_dir, ".osoji/shadow/src/x.py.shadow.md", "# Shadow\nPurpose: helpers.\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["shadow_doc_claim"].build(make_finding(), ctx)
    assert len(evidence) == 1
    assert evidence[0].payload["scope"] == "file"
    assert "Purpose: helpers." in evidence[0].payload["excerpt"]


def test_shadow_doc_builder_adds_directory_shadow_for_description_gaps(config, temp_dir):
    write(temp_dir, ".osoji/shadow/src/x.py.shadow.md", "file shadow\n")
    write(temp_dir, ".osoji/shadow/src/_directory.shadow.md", "directory shadow\n")
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(
        detector="debris:stale_comment", gap_type="description", symbol=None
    )
    evidence = BUILDERS["shadow_doc_claim"].build(finding, ctx)
    scopes = {e.payload["scope"] for e in evidence}
    assert scopes == {"file", "directory"}


# --- type_signature ---------------------------------------------------------


def test_type_signature_builder_matches_legacy_helpers(config, temp_dir):
    write(
        temp_dir,
        "src/models.py",
        "class CompletionOptions:\n    temperature: float | None = None\n",
    )
    symbols = {"src/models.py": [
        {"name": "CompletionOptions", "kind": "class", "line_start": 1, "line_end": 2},
    ]}
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file=symbols)
    finding = make_finding(
        detector="debris:latent_bug",
        gap_type="uncategorized",
        contract_claim="`CompletionOptions` has no field `top_k`",
        observed_behavior="access would raise AttributeError",
        symbol=None,
    )
    evidence = BUILDERS["type_signature"].build(finding, ctx)
    assert len(evidence) == 1
    payload = evidence[0].payload
    assert payload["type_name"] == "CompletionOptions"
    assert payload["file"] == "src/models.py"
    assert "class CompletionOptions" in payload["source"]


# --- robustness -------------------------------------------------------------


def test_builders_never_raise_on_missing_file(config):
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    finding = make_finding(path="does/not/exist.py")
    for kind, builder in BUILDERS.items():
        result = builder.build(finding, ctx)
        assert isinstance(result, list), kind


# --- cb-2 scanner_metadata steering (V1-5a) ----------------------------------


def _with_scanner_meta(finding, **payload):
    from osoji.evidence import Evidence

    return make_finding(
        **{
            **{k: getattr(finding, k) for k in (
                "detector", "gap_type", "path", "line_start", "line_end",
                "symbol", "contract_source", "contract_claim", "observed_behavior",
            )},
            "evidence": [Evidence(kind="scanner_metadata", payload=payload)],
        }
    )


def test_scanner_supplied_needles_override_symbol(config, temp_dir):
    # A dead-parameter finding: symbol `log.error` matches nothing textually;
    # the detector supplies the function's grep name instead.
    write(temp_dir, "src/x.py", "def log(msg, error=None):\n    pass\n")
    write(temp_dir, "src/y.py", "from x import log\nlog('boom')\n")
    finding = _with_scanner_meta(
        make_finding(symbol="log.error", line_start=1, line_end=1),
        scan_needles=["log"],
    )
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    assert len(evidence) == 1
    payload = evidence[0].payload
    assert payload["scan_scope"]["needles"] == ["log"]
    assert any(
        r["file"] == "src/y.py" and r["needle"] == "log"
        for r in payload["references"]
    )


def test_scanner_supplied_needles_feed_facts_lookups(config):
    facts = FakeFacts({"log": [
        {"file": "src/y.py", "kind": "call", "context": "log('boom')"},
    ]})
    finding = _with_scanner_meta(
        make_finding(symbol="log.error"), scan_needles=["log"]
    )
    ctx = BuildContext(config, facts_db=facts, symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    refs = [r for r in evidence[0].payload["references"] if r["source"] == "facts"]
    assert refs and refs[0]["file"] == "src/y.py"


def test_priority_paths_survive_the_hit_cap(config, temp_dir):
    # 25 one-hit files exceed _MAX_HITS_PER_NEEDLE=20; without priority the
    # deciding call site in zzz_caller.py (swept last) would be count-only.
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    for i in range(25):
        write(temp_dir, f"src/mod_{i:02d}.py", "# mentions old_helper\n")
    write(temp_dir, "src/zzz_caller.py", "from x import old_helper\nold_helper()\n")
    finding = _with_scanner_meta(
        make_finding(line_start=1, line_end=2),
        scan_needles=["old_helper"],
        priority_paths=["src/zzz_caller.py"],
    )
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    files = {r["file"] for r in evidence[0].payload["references"]}
    assert "src/zzz_caller.py" in files


def test_text_hit_inside_quoted_string_is_flagged(config, temp_dir):
    write(temp_dir, "src/x.py", "def old_helper():\n    pass\n")
    write(temp_dir, "src/y.py", "fn = getattr(mod, 'old_helper')\n")
    write(temp_dir, "src/z.py", "import x\nx.old_helper()\n")
    finding = make_finding(line_start=1, line_end=2)
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    by_file = {r["file"]: r for r in evidence[0].payload["references"]}
    assert by_file["src/y.py"].get("in_string_literal") is True
    assert "in_string_literal" not in by_file["src/z.py"]


def test_match_in_quotes_positional_check():
    from osoji.evidence_builders import _match_in_quotes

    line = "dispatch = {'old_helper': fn}  # old_helper"
    assert _match_in_quotes(line, line.index("old_helper")) is True
    assert _match_in_quotes(line, line.rindex("old_helper")) is False
    escaped = 'msg = "say \\"old_helper\\" now"'
    assert _match_in_quotes(escaped, escaped.index("old_helper")) is True
    assert _match_in_quotes("old_helper()", 0) is False


def test_backticked_dotted_names_yield_qualified_and_bare_needles(config, temp_dir):
    # dead_symbol-001 lesson: the plain-word backtick pattern skipped dotted
    # names entirely, so the method was never swept and its string-dispatch
    # site stayed invisible.
    write(temp_dir, "src/x.py", "class Widget:\n    def render(self):\n        pass\n")
    write(temp_dir, "src/reg.py", "handler = getattr(w, 'render')\n")
    finding = make_finding(
        symbol=None,
        line_start=1,
        line_end=3,
        contract_claim="Symbol `Widget.render` is declared but appears unused",
        observed_behavior="no references to `Widget.render` were found",
    )
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    scope = evidence[0].payload["scan_scope"]
    assert "Widget.render" in scope["needles"]
    assert "render" in scope["needles"]
    hits = [r for r in evidence[0].payload["references"] if r["file"] == "src/reg.py"]
    assert hits and hits[0].get("in_string_literal") is True


def test_sweep_orders_by_proximity_to_flagged_file(config, temp_dir):
    # V1-5a dead_symbol-002 lesson: a committed corpus's own JSON artifacts
    # (source-ranked extensions) crowded out the flagged file's sibling-package
    # usage sites. Proximity to the flagged file breaks the tie.
    write(temp_dir, "src/pkg/x.py", "class Base:\n    pass\n")
    write(temp_dir, "src/pkg/impl.py", "from x import Base\nclass Impl(Base):\n    pass\n")
    # A far-away fixture corpus with more than enough hits to fill the cap
    for i in range(30):
        write(temp_dir, f"tests/fixtures/trace_{i:02d}.json", '{"note": "mentions Base"}\n')
    finding = make_finding(
        path="src/pkg/x.py", symbol="Base", line_start=1, line_end=2
    )
    ctx = BuildContext(config, facts_db=FakeFacts(), symbols_by_file={})
    evidence = BUILDERS["cross_file_reference"].build(finding, ctx)
    files = [r["file"] for r in evidence[0].payload["references"]]
    assert files[0] == "src/pkg/impl.py"
