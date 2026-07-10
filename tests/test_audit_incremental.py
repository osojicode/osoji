"""End-to-end tests for the V1-9 incremental audit path.

Strategy: run the real ``run_audit_async`` orchestration with only the
obligations phase enabled (a deterministic heuristic propose stage plus one
Triage seam) and a canned provider. The equivalence contract: an incremental
re-run on an unchanged tree serves every verdict from the manifest cache —
zero LLM calls, identical issues, ``verdict_cache_hit_rate == 1.0``.

Assertions check hit counts and manifest content, not just absence of errors:
the audit phases are best-effort (broad try/excepts) and would swallow a
broken session silently.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from osoji.audit import _run_phase3_async, run_audit_async
from osoji.audit_manifest import (
    VerdictSession,
    cache_from_verdicts,
    current_version,
    load_manifest,
    write_manifest,
)
from osoji.claim_builder import build_debris_claims
from osoji.cli import main
from osoji.config import Config
from osoji.llm.types import CompletionResult, ToolCall

# --- environment helpers (mold of test_audit_obligations_cutover) -------------


def _write(temp_dir: Path, rel: str, text: str) -> None:
    path = temp_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_facts(temp_dir: Path, source: str, string_literals: list[dict]) -> None:
    facts_file = temp_dir / ".osoji" / "facts" / (source + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    facts_file.write_text(json.dumps({
        "source": source,
        "source_hash": "abc123",
        "imports": [],
        "exports": [],
        "calls": [],
        "string_literals": string_literals,
    }), encoding="utf-8")


def _one_implicit_contract_env(temp_dir: Path) -> None:
    _write(temp_dir, "src/producer.py", "def emit():\n    return 'my_category'\n")
    _write(temp_dir, "src/consumer.py", "def handle(x):\n    return x == 'my_category'\n")
    _write_facts(temp_dir, "src/producer.py", [
        {"value": "my_category", "context": "appended to list", "line": 2,
         "kind": "identifier", "usage": "produced"},
    ])
    _write_facts(temp_dir, "src/consumer.py", [
        {"value": "my_category", "context": "membership check", "line": 2,
         "kind": "identifier", "usage": "checked"},
    ])


class FakeProvider:
    """Canned submit_triage_verdicts provider; counts calls."""

    def __init__(self, verdicts=None, error=None):
        self.calls = 0
        self._verdicts = verdicts
        self._error = error

    async def complete(self, messages, system, options):
        self.calls += 1
        if self._error is not None:
            raise self._error
        verdicts = self._verdicts
        if verdicts is None:
            validator = options.tool_input_validators[0]
            n = len(validator("submit_triage_verdicts", {"verdicts": []}))
            verdicts = [
                {"batch_index": i, "verdict": "confirmed", "confidence": 0.9,
                 "reasoning": "genuine contract"}
                for i in range(n)
            ]
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id=f"tc{self.calls}", name="submit_triage_verdicts",
                input={"verdicts": verdicts},
            )],
            input_tokens=140, output_tokens=70,
            model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


_EXCLUDE = {"shadow", "doc-analysis", "debris"}


def _run_audit(temp_dir, provider, **kwargs):
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    if kwargs.pop("force", False):
        config.force = True
    with patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        result = asyncio.run(run_audit_async(
            config,
            fix_shadow=False,
            obligations=True,
            exclude=_EXCLUDE,
            **kwargs,
        ))
    return config, result


def _obligation_issues(result):
    return sorted(
        (i.path, i.category, i.message)
        for i in result.issues
        if i.exclude_key == "obligations"
    )


# --- day-zero manifest write --------------------------------------------------


def test_day_zero_run_writes_manifest(temp_dir):
    _one_implicit_contract_env(temp_dir)
    provider = FakeProvider()

    config, _result = _run_audit(temp_dir, provider)

    assert provider.calls == 1
    manifest = load_manifest(config.audit_manifest_path)
    assert manifest is not None
    assert manifest["osoji_version"] == current_version()
    assert manifest["verdicts"], "day-zero run must harvest verdicts"
    entry = next(iter(manifest["verdicts"].values()))
    assert entry["detector"].startswith("obligations:")
    assert entry["verdict"] == "confirmed"
    assert entry["evidence_fingerprint"]


# --- the equivalence contract ---------------------------------------------------


def test_incremental_rerun_serves_cache_and_matches_day_zero(temp_dir):
    _one_implicit_contract_env(temp_dir)

    config1, result1 = _run_audit(temp_dir, FakeProvider())

    erroring = FakeProvider(error=RuntimeError("LLM must not be called"))
    config2, result2 = _run_audit(temp_dir, erroring, incremental=True)

    assert erroring.calls == 0
    assert _obligation_issues(result2) == _obligation_issues(result1)
    assert result2.scorecard.verdict_cache_hit_rate == 1.0
    # Manifest survives the rerun with the same verdicts
    manifest = load_manifest(config2.audit_manifest_path)
    assert manifest["verdicts"] == load_manifest(config1.audit_manifest_path)["verdicts"]


def test_plain_rerun_does_not_read_cache(temp_dir):
    _one_implicit_contract_env(temp_dir)
    _run_audit(temp_dir, FakeProvider())

    provider = FakeProvider()
    _config, result = _run_audit(temp_dir, provider)  # no incremental flag

    assert provider.calls == 1
    assert result.scorecard.verdict_cache_hit_rate in (None, 0.0)


def test_stale_osoji_version_forces_day_zero(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config1, _ = _run_audit(temp_dir, FakeProvider())
    manifest = load_manifest(config1.audit_manifest_path)
    write_manifest(
        config1.audit_manifest_path, manifest["verdicts"],
        commit=None, version="cb-0:stale",
    )

    provider = FakeProvider()
    _config2, result2 = _run_audit(temp_dir, provider, incremental=True)

    assert provider.calls == 1
    assert result2.scorecard.verdict_cache_hit_rate == 0.0


def test_force_wins_over_incremental(temp_dir):
    _one_implicit_contract_env(temp_dir)
    _run_audit(temp_dir, FakeProvider())

    provider = FakeProvider()
    _config2, _result2 = _run_audit(temp_dir, provider, incremental=True, force=True)

    assert provider.calls == 1


# --- producer-scoped manifest merge --------------------------------------------


def test_merge_keeps_foreign_producers_and_drops_disappeared(temp_dir):
    _one_implicit_contract_env(temp_dir)
    config1, _ = _run_audit(temp_dir, FakeProvider())
    manifest = load_manifest(config1.audit_manifest_path)
    verdicts = dict(manifest["verdicts"])
    verdicts["foreign-id"] = {
        "detector": "deadcode:dead_symbol", "evidence_fingerprint": "fp-x",
        "verdict": "confirmed", "confidence": 0.9, "triage_reasoning": "r",
        "suggested_fix": None, "severity": "warning", "contract_class": None,
    }
    verdicts["vanished-obligation"] = {
        "detector": "obligations:obligation_implicit_contract",
        "evidence_fingerprint": "fp-y", "verdict": "confirmed",
        "confidence": 0.9, "triage_reasoning": "r", "suggested_fix": None,
        "severity": "warning", "contract_class": None,
    }
    write_manifest(config1.audit_manifest_path, verdicts,
                   commit=None, version=current_version())

    config2, _ = _run_audit(temp_dir, FakeProvider(), incremental=True)

    rewritten = load_manifest(config2.audit_manifest_path)["verdicts"]
    assert "foreign-id" in rewritten  # deadcode did not run -> preserved
    assert "vanished-obligation" not in rewritten  # obligations ran -> dropped
    assert any(e["detector"].startswith("obligations:") for e in rewritten.values())


# --- debris seam (Phase 3, chunked via decide_junk_claims since work#57) --------


class _FakeFacts:
    """FactsDB stand-in: every symbol has one stable cross-file reference."""

    def cross_file_references(self, symbol, source_path):
        return [{"file": "src/y.py", "kind": "import", "context": "uses it",
                 "resolves_to_source": True}]


def _debris_env(temp_dir):
    _write(temp_dir, "src/lib.py", "def build():\n    return 1\n# unreachable\n")
    return [{
        "source": "src/x.py",
        "source_path": Path("src/x.py"),
        "category": "dead_code",
        "line_start": 1,
        "line_end": 2,
        "severity": "warning",
        "description": "build() is unreachable",
    }]


def test_debris_seam_serves_cache_without_llm(temp_dir):
    raw_debris = _debris_env(temp_dir)
    config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
    with patch("osoji.facts.FactsDB", return_value=_FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}):
        claims, _indices, _we = build_debris_claims(config, raw_debris)
    assert claims, "debris env must yield one eligible claim"
    cache = {
        (c.finding.id, c.finding.evidence_fingerprint): {
            "verdict": "dismissed", "confidence": 0.9,
            "triage_reasoning": "cached dismissal", "suggested_fix": None,
            "severity": "warning", "contract_class": None,
        }
        for c in claims
    }
    session = VerdictSession(cache=cache)
    config.verdict_session = session
    provider = FakeProvider(error=RuntimeError("LLM must not be called"))

    with patch("osoji.facts.FactsDB", return_value=_FakeFacts()), \
         patch("osoji.symbols.load_all_symbols", return_value={}), \
         patch("osoji.audit.create_runtime", return_value=(provider, MagicMock())):
        suppressed, _tokens = asyncio.run(
            _run_phase3_async(config, raw_debris, MagicMock(), False)
        )

    assert provider.calls == 0
    assert suppressed == {0}  # cached dismissed verdict suppresses
    assert session.cache_hits == len(claims)
    assert session.harvested  # cached verdicts are re-harvested for the rewrite


# --- CLI surface -----------------------------------------------------------------


def test_cli_since_outside_git_repo_fails_cleanly(temp_dir):
    runner = CliRunner()

    result = runner.invoke(main, ["audit", str(temp_dir), "--since", "HEAD~1"])

    assert result.exit_code != 0
    assert "git repository" in result.output


def test_cli_audit_help_shows_incremental_flags():
    runner = CliRunner()

    result = runner.invoke(main, ["audit", "--help"])

    assert result.exit_code == 0
    assert "--incremental" in result.output
    assert "--since" in result.output
