"""Tests for src/osoji/corpus_emit.py -- the `osoji corpus emit` CLI seam.

Builds a fabricated repo under ``tmp_path`` (a few source files, a
decided-findings ledger, and sidecars for one file) and exercises
``emit_case``/``resolve_dest`` directly, then round-trips an emitted case
through ``eval_lib.load_corpus``/``stage_case`` (Task 3-5's corpus loader) to
prove the stub is actually corpus-shaped, not just plausible-looking JSON.
Fully deterministic -- no LLM calls, no network.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from eval_lib import load_corpus, stage_case  # noqa: E402

from osoji.cli import main  # noqa: E402
from osoji.corpus_emit import (  # noqa: E402
    ENV_CORPUS_DEST,
    MAX_FILES,
    CorpusEmitError,
    _category_of,
    emit_case,
    resolve_dest,
)
from osoji.evidence import Evidence  # noqa: E402
from osoji.findings import Finding  # noqa: E402


# ---------------------------------------------------------------------------
# fabricated-repo helpers
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _make_finding(**overrides) -> Finding:
    base = dict(
        detector="deadcode:dead_symbol",
        gap_type="reachability",
        path="src/app/util.py",
        line_start=10,
        line_end=12,
        symbol="unused_helper",
        contract_source="declared",
        contract_claim="unused_helper is defined but never used",
        observed_behavior="no references found in the scanned corpus",
        evidence=[],
        verdict=None,
        confidence=None,
        triage_reasoning=None,
        suggested_fix=None,
        severity=None,
        contract_class=None,
        evidence_fingerprint=None,
    )
    base.update(overrides)
    return Finding(**base)


def _build_repo(tmp_path: Path) -> tuple[Path, Finding, Finding]:
    """A fabricated repo with a decided-findings ledger holding two findings:
    ``confirmed`` (with evidence referencing a second file) and
    ``uncertain`` (undecided -- exercises the expected-verdict guard).
    Sidecars are written for ``src/app/util.py`` only.
    """

    repo = tmp_path / "repo"
    _write(repo, "src/app/util.py", "def unused_helper():\n    pass\n")
    _write(repo, "src/app/caller.py", "# mentions unused_helper in a comment\n")
    _write(repo, "README.md", "# demo repo\n")

    confirmed = _make_finding(
        symbol="unused_helper",
        verdict="confirmed",
        confidence=0.9,
        triage_reasoning="no live path found",
        suggested_fix="remove it",
        severity="warning",
        evidence=[
            Evidence(
                kind="cross_file_reference",
                payload={
                    "references": [
                        {"file": "src/app/caller.py", "kind": "comment", "context": "mentions it"},
                    ]
                },
            )
        ],
    )
    uncertain = _make_finding(
        symbol="other_helper",
        line_start=20,
        line_end=22,
        contract_claim="other_helper is defined but never used",
        verdict="uncertain",
        confidence=0.3,
        triage_reasoning="insufficient evidence",
        evidence=[],
    )

    ledger = {
        "schema": "decided-findings/1",
        "commit": "abc123def456",
        "generated_at": "2026-07-21T00:00:00+00:00",
        "findings": [confirmed.to_dict(), uncertain.to_dict()],
    }
    _write(repo, ".osoji/analysis/decided-findings.json", json.dumps(ledger, indent=2))

    _write(repo, ".osoji/symbols/src/app/util.py.symbols.json", "{}")
    _write(repo, ".osoji/facts/src/app/util.py.facts.json", "{}")
    _write(repo, ".osoji/shadow/src/app/util.py.shadow.md", "# util.py shadow\n")

    return repo, confirmed, uncertain


# ---------------------------------------------------------------------------
# emit_case -- happy path / full stub layout
# ---------------------------------------------------------------------------


def test_emit_case_creates_full_stub_layout(tmp_path):
    repo, confirmed, uncertain = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    case_dir = emit_case(repo, confirmed.id, "unused-helper", dest)

    assert case_dir == dest / "dead_symbol" / "case_unused-helper"
    assert case_dir.exists()

    # source/: the flagged file plus the evidence-referenced file, nothing else.
    source_files = sorted(
        p.relative_to(case_dir / "source").as_posix()
        for p in (case_dir / "source").rglob("*")
        if p.is_file()
    )
    assert source_files == ["src/app/caller.py", "src/app/util.py"]

    # sidecars: only util.py had any; caller.py has none.
    assert (case_dir / "symbols" / "src" / "app" / "util.py.symbols.json").is_file()
    assert (case_dir / "facts" / "src" / "app" / "util.py.facts.json").is_file()
    assert (case_dir / "shadow" / "src" / "app" / "util.py.shadow.md").is_file()
    assert not (case_dir / "symbols" / "src" / "app" / "caller.py.symbols.json").exists()

    case_json = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    assert case_json["schema"] == "corpus-case/1"
    assert case_json["slug"] == "unused-helper"
    assert case_json["category"] == "dead_symbol"
    assert case_json["detector"] == "deadcode"
    assert case_json["gap_type"] == "reachability"
    assert case_json["language"] == "python"
    assert case_json["snapshot_ref"] is None
    assert case_json["evidence_policy"] == "rebuild"
    assert case_json["origin"]["repo"] == repo.name
    assert case_json["origin"]["remote"] is None  # not a git repo
    assert case_json["origin"]["commit"] == "unknown"  # not a git repo
    assert case_json["origin"]["osoji_version"]
    assert case_json["origin"]["sweep_run"] is None

    finding_json = json.loads((case_dir / "finding.json").read_text(encoding="utf-8"))
    assert finding_json["path"] == "src/app/util.py"
    assert "\\" not in finding_json["path"]
    assert finding_json["symbol"] == "unused_helper"
    assert finding_json["id"] == confirmed.id
    for key in (
        "verdict", "confidence", "triage_reasoning", "suggested_fix",
        "severity", "contract_class", "evidence_fingerprint",
    ):
        assert finding_json[key] is None, key
    assert finding_json["evidence"] == []

    expected_json = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected_json["schema"] == "corpus-expected/1"
    assert expected_json["verdict"] == "confirmed"
    assert expected_json["reasoning"] == "no live path found"
    assert expected_json["gray"] is False
    assert expected_json["gray_reason"] is None
    assert expected_json["expected_contract_class"] is None
    assert expected_json["adjudicated_by"] == "sweep-proposed"
    assert expected_json["accepted"] is False


def test_emit_case_language_default_and_override(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    default_dir = emit_case(repo, confirmed.id, "lang-default", dest)
    assert json.loads((default_dir / "case.json").read_text())["language"] == "python"

    override_dir = emit_case(repo, confirmed.id, "lang-override", dest, language="custom-lang")
    assert json.loads((override_dir / "case.json").read_text())["language"] == "custom-lang"


def test_emit_case_include_adds_extra_file(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    _write(repo, "docs/notes.md", "notes\n")
    dest = tmp_path / "corpus" / "_holding"

    case_dir = emit_case(repo, confirmed.id, "with-include", dest, include=["docs/notes.md"])

    assert (case_dir / "source" / "docs" / "notes.md").is_file()


def test_emit_case_reasoning_and_gray_overrides_win(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    case_dir = emit_case(
        repo, confirmed.id, "override-case", dest,
        reasoning="human override reasoning", gray=True,
    )

    expected_json = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected_json["reasoning"] == "human override reasoning"
    assert expected_json["gray"] is True


def test_emit_case_expected_verdict_override_wins_over_decided(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    case_dir = emit_case(repo, confirmed.id, "flip-verdict", dest, expected_verdict="dismissed")

    expected_json = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected_json["verdict"] == "dismissed"


# ---------------------------------------------------------------------------
# emit_case -- error cases
# ---------------------------------------------------------------------------


def test_emit_case_missing_ledger_raises_clear_error(tmp_path):
    repo = tmp_path / "no_audit_repo"
    repo.mkdir()
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="osoji audit"):
        emit_case(repo, "whatever", "some-slug", dest)


def test_emit_case_missing_id_raises_with_near_miss_listing(tmp_path):
    repo, confirmed, uncertain = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError) as excinfo:
        emit_case(repo, "not-a-real-id", "whatever", dest)

    message = str(excinfo.value)
    assert "not-a-real-id" in message
    assert confirmed.path in message
    assert confirmed.id in message
    assert uncertain.id in message
    assert not (dest / "dead_symbol" / "case_whatever").exists()


def test_emit_case_uncertain_verdict_requires_expected_verdict_override(tmp_path):
    repo, confirmed, uncertain = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="expected-verdict"):
        emit_case(repo, uncertain.id, "uncertain-case", dest)

    # nothing partially written
    assert not (dest / "dead_symbol" / "case_uncertain-case").exists()

    case_dir = emit_case(repo, uncertain.id, "uncertain-case", dest, expected_verdict="dismissed")
    expected_json = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected_json["verdict"] == "dismissed"


def test_emit_case_bad_slug_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="slug"):
        emit_case(repo, confirmed.id, "Not A Valid Slug!", dest)


def test_emit_case_include_nonexistent_file_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="does not exist"):
        emit_case(repo, confirmed.id, "bad-include", dest, include=["does/not/exist.py"])

    assert not (dest / "dead_symbol" / "case_bad-include").exists()


def test_emit_case_duplicate_dir_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    emit_case(repo, confirmed.id, "dup-slug", dest)

    with pytest.raises(CorpusEmitError, match="already exists"):
        emit_case(repo, confirmed.id, "dup-slug", dest)


def test_emit_case_file_cap_exceeded_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)

    refs = []
    for i in range(MAX_FILES + 5):
        rel = f"src/extra/file_{i}.py"
        _write(repo, rel, f"# extra {i}\n")
        refs.append({"file": rel, "kind": "import", "context": "referenced"})

    big = _make_finding(
        symbol="big_symbol",
        contract_claim="big claim referencing many files",
        verdict="confirmed",
        triage_reasoning="r",
        evidence=[Evidence(kind="cross_file_reference", payload={"references": refs})],
    )
    ledger_path = repo / ".osoji" / "analysis" / "decided-findings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["findings"].append(big.to_dict())
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    dest = tmp_path / "corpus" / "_holding"
    with pytest.raises(CorpusEmitError, match="exceeds the corpus-emit cap") as excinfo:
        emit_case(repo, big.id, "too-big", dest)

    # --include is additive-only -- it can never narrow the file set below
    # the cap, so the error must not suggest it as a fix. The message should
    # instead be honest that there is no narrowing knob today.
    message = str(excinfo.value)
    assert "--include" not in message
    assert "too many files" in message or "targeted evidence" in message

    assert not (dest / "dead_symbol" / "case_too-big").exists()


def test_emit_case_missing_finding_path_file_names_no_such_file(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    # Delete the flagged file after it was decided -- a realistic, if rare,
    # race between an audit run and an `osoji corpus emit` call.
    (repo / "src" / "app" / "util.py").unlink()
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="no such file") as excinfo:
        emit_case(repo, confirmed.id, "missing-file", dest)

    assert "outside the repo" not in str(excinfo.value)
    # The finding-path check used to live inside the
    # copy loop, so an alphabetically-earlier file (caller.py, from
    # confirmed's evidence) was already copied under case_dir by the time
    # util.py's absence raised -- leaving a half-written case directory
    # behind. Now validated pre-flight, before case_dir is created at all.
    assert not (dest / "dead_symbol" / "case_missing-file").exists()


def test_emit_case_finding_path_escaping_repo_names_outside_repo(tmp_path):
    repo, confirmed, uncertain = _build_repo(tmp_path)
    ledger_path = repo / ".osoji" / "analysis" / "decided-findings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for f in ledger["findings"]:
        if f["id"] == confirmed.id:
            f["path"] = "../outside.py"  # escapes the repo tree
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="outside the repo") as excinfo:
        emit_case(repo, confirmed.id, "escaping-path", dest)

    assert "no such file" not in str(excinfo.value)
    assert not (dest / "dead_symbol" / "case_escaping-path").exists()


def test_emit_case_mid_copy_failure_removes_partial_case_dir(tmp_path, monkeypatch):
    # Belt-and-suspenders coverage: pre-flight validation passes (every path
    # genuinely exists at that moment), but the second file's copy raises
    # anyway -- simulating the residual race pre-flight cannot rule out (a
    # file vanishing, a permission error, a full disk between the check and
    # the write). The cleanup-on-failure wrapper must remove case_dir rather
    # than leave the first file's copy behind.
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    import osoji.corpus_emit as corpus_emit_module

    real_copy2 = shutil.copy2
    call_count = {"n": 0}

    def flaky_copy2(src, dst, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated mid-copy failure")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(corpus_emit_module.shutil, "copy2", flaky_copy2)

    with pytest.raises(OSError, match="simulated mid-copy failure"):
        emit_case(repo, confirmed.id, "mid-copy-fail", dest)

    assert not (dest / "dead_symbol" / "case_mid-copy-fail").exists()


# ---------------------------------------------------------------------------
# --exclude narrowing knob + snapshot exclusion + path-length error
# (osojicode/work#85)
# ---------------------------------------------------------------------------


def _append_finding(repo: Path, finding: Finding) -> None:
    ledger_path = repo / ".osoji" / "analysis" / "decided-findings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["findings"].append(finding.to_dict())
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")


def _over_cap_finding(repo: Path) -> Finding:
    """A finding whose evidence references MAX_FILES+5 real files under
    ``src/extra/`` (over the cap) plus the default ``src/app/util.py`` path."""

    refs = []
    for i in range(MAX_FILES + 5):
        rel = f"src/extra/file_{i}.py"
        _write(repo, rel, f"# extra {i}\n")
        refs.append({"file": rel, "kind": "import", "context": "referenced"})
    big = _make_finding(
        symbol="big_symbol",
        contract_claim="big claim referencing many files",
        verdict="confirmed",
        triage_reasoning="r",
        evidence=[Evidence(kind="cross_file_reference", payload={"references": refs})],
    )
    _append_finding(repo, big)
    return big


def test_emit_case_exclude_narrows_over_cap_finding(tmp_path):
    repo, _, _ = _build_repo(tmp_path)
    big = _over_cap_finding(repo)
    dest = tmp_path / "corpus" / "_holding"

    # Without --exclude the finding is over-cap and cannot be emitted.
    with pytest.raises(CorpusEmitError, match="exceeds the corpus-emit cap"):
        emit_case(repo, big.id, "over-cap", dest)

    # --exclude drops the src/extra/* evidence files BEFORE the cap check,
    # bringing the set under MAX_FILES so the case emits.
    case_dir = emit_case(repo, big.id, "narrowed", dest, exclude=["src/extra/*.py"])
    assert case_dir.exists()

    source_files = sorted(
        p.relative_to(case_dir / "source").as_posix()
        for p in (case_dir / "source").rglob("*")
        if p.is_file()
    )
    # the finding's own flagged path survives; the excluded evidence is gone
    assert "src/app/util.py" in source_files
    assert not any(s.startswith("src/extra/") for s in source_files)


def test_emit_case_exclude_exact_path_narrows(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    # confirmed's evidence references src/app/caller.py; exclude it by exact path.
    case_dir = emit_case(
        repo, confirmed.id, "exact-exclude", dest, exclude=["src/app/caller.py"]
    )
    source_files = sorted(
        p.relative_to(case_dir / "source").as_posix()
        for p in (case_dir / "source").rglob("*")
        if p.is_file()
    )
    assert source_files == ["src/app/util.py"]


def test_emit_case_exclude_own_path_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    with pytest.raises(CorpusEmitError, match="finding's own path"):
        emit_case(repo, confirmed.id, "exclude-self", dest, exclude=["src/app/util.py"])

    assert not (dest / "dead_symbol" / "case_exclude-self").exists()


def test_emit_case_exclude_glob_matching_own_path_raises(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    # A glob that also swallows the finding's own path is rejected too.
    with pytest.raises(CorpusEmitError, match="finding's own path"):
        emit_case(repo, confirmed.id, "exclude-glob-self", dest, exclude=["src/app/*.py"])


def test_emit_case_drops_evidence_under_corpus_snapshot(tmp_path):
    repo, _, _ = _build_repo(tmp_path)

    # A committed corpus-case snapshot living inside the repo (short paths, so
    # that WITHOUT the fix the frozen file is copied and enumerable -- the
    # assertion below then genuinely fails, rather than being masked by the
    # Windows MAX_PATH crash the fix exists to prevent).
    _write(repo, "data/case_001/case.json", '{"schema": "corpus-case/1", "slug": "x"}\n')
    _write(repo, "data/case_001/source/frozen.py", "def frozen():\n    pass\n")

    finding = _make_finding(
        symbol="snapshot_ref_symbol",
        contract_claim="references a frozen corpus-snapshot file",
        line_start=50,
        line_end=52,
        verdict="confirmed",
        triage_reasoning="r",
        evidence=[
            Evidence(
                kind="cross_file_reference",
                payload={
                    "references": [
                        {"file": "src/app/caller.py", "kind": "comment", "context": "x"},
                        {
                            "file": "data/case_001/source/frozen.py",
                            "kind": "import",
                            "context": "x",
                        },
                    ]
                },
            )
        ],
    )
    _append_finding(repo, finding)
    dest = tmp_path / "corpus" / "_holding"

    case_dir = emit_case(repo, finding.id, "drops-snapshot", dest)
    source_files = sorted(
        p.relative_to(case_dir / "source").as_posix()
        for p in (case_dir / "source").rglob("*")
        if p.is_file()
    )
    # the live evidence file is kept; the corpus-snapshot evidence file dropped
    assert "src/app/caller.py" in source_files
    assert not any("case_001" in s for s in source_files)


def test_emit_case_path_length_failure_gives_readable_error(tmp_path, monkeypatch):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"

    import osoji.corpus_emit as corpus_emit_module

    def raise_path_too_long(src, dst, *args, **kwargs):
        err = OSError("The filename or extension is too long")
        err.winerror = 206  # ERROR_FILENAME_EXCED_RANGE
        raise err

    monkeypatch.setattr(corpus_emit_module.shutil, "copy2", raise_path_too_long)

    with pytest.raises(CorpusEmitError) as excinfo:
        emit_case(repo, confirmed.id, "too-long", dest)

    message = str(excinfo.value)
    assert "--exclude" in message
    # the offending destination path is named
    assert "case_too-long" in message
    # cleanup-on-failure still ran -- no half-written case directory left
    assert not (dest / "dead_symbol" / "case_too-long").exists()


# ---------------------------------------------------------------------------
# category derivation (osojicode/work#75: suffix-derived, matches the
# accepted corpus directories)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("detector", "expected_category"),
    [
        # JunkAnalyzer-backed producers (findings_adapter.py's detector
        # literals): the category is the detector's ``:category`` suffix,
        # which is exactly how the accepted corpus directories are named
        # (dead_symbol/, dead_parameter/, unactuated_config/, ...).
        ("deadcode:dead_symbol", "dead_symbol"),
        ("deadparam:dead_parameter", "dead_parameter"),
        ("plumbing:unactuated_config", "unactuated_config"),
        ("orphan:orphaned_file", "orphaned_file"),
        ("deps:dead_dependency", "dead_dependency"),
        ("cicd:dead_cicd", "dead_cicd"),
        # obligations: suffixes arrive already obligation_-prefixed
        # (findings_adapter.py prepends it), matching the corpus dirs.
        ("obligations:obligation_violation", "obligation_violation"),
        ("obligations:obligation_implicit_contract", "obligation_implicit_contract"),
        # doc: suffixes arrive UNprefixed (DocFinding.category), but the
        # corpus dirs and the scorecard spelling (audit.py's
        # ``f"doc_{finding.category}"``) carry the doc_ prefix.
        ("doc:stale_content", "doc_stale_content"),
        ("doc:misleading_claim", "doc_misleading_claim"),
        # debris:<category> (findings_adapter.py's finding_from_debris):
        # today's live tools.py schema enum, plus the corpus README's
        # "legacy bespoke case dirs" names (dead_params, plumbing) that
        # predate that schema -- the legacy debris vocabulary round-trips
        # as itself, which is how the accepted corpus stores debris cases
        # (dead_code/, latent_bug/) alongside the fine-grained detector
        # dirs (dead_symbol/, unactuated_config/).
        ("debris:dead_code", "dead_code"),
        ("debris:latent_bug", "latent_bug"),
        ("debris:stale_comment", "stale_comment"),
        ("debris:misleading_docstring", "misleading_docstring"),
        ("debris:commented_out_code", "commented_out_code"),
        ("debris:expired_todo", "expired_todo"),
        ("debris:dead_params", "dead_params"),
        ("debris:plumbing", "plumbing"),
    ],
)
def test_category_of_derives_category_from_detector_suffix(detector, expected_category):
    assert _category_of(detector) == expected_category


# ---------------------------------------------------------------------------
# resolve_dest
# ---------------------------------------------------------------------------


def test_resolve_dest_prefers_explicit_override(tmp_path):
    assert resolve_dest(tmp_path, tmp_path / "custom_dest") == tmp_path / "custom_dest"


def test_resolve_dest_uses_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CORPUS_DEST, str(tmp_path / "env_dest"))

    assert resolve_dest(tmp_path, None) == tmp_path / "env_dest"


def test_resolve_dest_defaults_to_holding_when_corpus_present(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CORPUS_DEST, raising=False)
    (tmp_path / "tests" / "fixtures" / "prompt_regression").mkdir(parents=True)

    result = resolve_dest(tmp_path, None)

    assert result == tmp_path / "tests" / "fixtures" / "prompt_regression" / "_holding"


def test_resolve_dest_raises_when_nothing_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CORPUS_DEST, raising=False)

    with pytest.raises(CorpusEmitError, match=ENV_CORPUS_DEST):
        resolve_dest(tmp_path, None)


# ---------------------------------------------------------------------------
# integration: emitted stub round-trips through eval_lib after acceptance
# ---------------------------------------------------------------------------


def test_emitted_case_loads_and_stages_after_acceptance(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    corpus_root = tmp_path / "corpus"
    dest = corpus_root / "_holding"

    case_dir = emit_case(repo, confirmed.id, "accepted-case", dest)

    # Acceptance flow (README): flip accepted -> true, git mv into
    # <category>/case_NNN_<slug>. Never touches the real corpus tree.
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["accepted"] = True
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    accepted_dir = corpus_root / "dead_symbol" / "case_101_accepted-case"
    accepted_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(case_dir), str(accepted_dir))

    cases = load_corpus(corpus_root)
    assert len(cases) == 1
    case = cases[0]
    assert case.key == "dead_symbol/case_101_accepted-case"
    assert case.finding.symbol == "unused_helper"
    assert case.expected_verdict == "confirmed"

    workdir = tmp_path / "work"
    config = stage_case(case, workdir)

    assert (config.root_path / "src" / "app" / "util.py").exists()
    assert (config.root_path / "src" / "app" / "caller.py").exists()
    assert (config.root_path / ".osoji" / "symbols" / "src" / "app" / "util.py.symbols.json").exists()
    assert (config.root_path / ".osoji" / "facts" / "src" / "app" / "util.py.facts.json").exists()
    assert (config.root_path / ".osoji" / "shadow" / "src" / "app" / "util.py.shadow.md").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_corpus_emit_help():
    runner = CliRunner()

    result = runner.invoke(main, ["corpus", "emit", "--help"])

    assert result.exit_code == 0
    assert "--id" in result.output
    assert "--slug" in result.output


def test_cli_corpus_emit_bad_slug_errors(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, [
        "corpus", "emit", str(repo),
        "--id", confirmed.id, "--slug", "Bad Slug!",
        "--dest", str(tmp_path / "dest"),
    ])

    assert result.exit_code != 0
    assert "slug" in result.output.lower()


def test_cli_corpus_emit_missing_dest_resolution_errors(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CORPUS_DEST, raising=False)
    repo = tmp_path / "plain_repo"
    repo.mkdir()
    runner = CliRunner()

    result = runner.invoke(main, [
        "corpus", "emit", str(repo),
        "--id", "whatever", "--slug", "some-slug",
    ])

    assert result.exit_code != 0
    assert ENV_CORPUS_DEST in result.output


def test_cli_corpus_emit_creates_case_and_prints_reminder(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"
    runner = CliRunner()

    result = runner.invoke(main, [
        "corpus", "emit", str(repo),
        "--id", confirmed.id, "--slug", "cli-case",
        "--dest", str(dest),
    ])

    assert result.exit_code == 0, result.output
    assert "git mv" in result.output
    assert (dest / "dead_symbol" / "case_cli-case" / "case.json").exists()


def test_cli_corpus_emit_exclude_flag_drops_evidence_file(tmp_path):
    repo, confirmed, _ = _build_repo(tmp_path)
    dest = tmp_path / "corpus" / "_holding"
    runner = CliRunner()

    result = runner.invoke(main, [
        "corpus", "emit", str(repo),
        "--id", confirmed.id, "--slug", "cli-exclude",
        "--dest", str(dest),
        "--exclude", "src/app/caller.py",
    ])

    assert result.exit_code == 0, result.output
    case_dir = dest / "dead_symbol" / "case_cli-exclude"
    assert (case_dir / "source" / "src" / "app" / "util.py").is_file()
    assert not (case_dir / "source" / "src" / "app" / "caller.py").exists()
