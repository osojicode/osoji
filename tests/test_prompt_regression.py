"""Prompt regression tests using real LLM calls against snapshotted files.

These tests verify that prompt changes don't regress on known edge cases.
They make real API calls and are gated behind the 'prompt_regression' marker.

Run with: pytest -m prompt_regression
Skipped by default in normal 'pytest' runs.
"""

import json
import shutil
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.deadcode import DeadCodeCandidate, _verify_batch_async, scan_references
from docstar.llm.factory import create_provider
from docstar.tools import get_dead_code_tool_definitions

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompt_regression"


def _setup_case_dir(tmp_path: Path, case_dir: Path) -> Config:
    """Copy snapshotted source files into a temp project dir and return a Config."""
    source_dir = case_dir / "source"
    symbols_dir = case_dir / "symbols"

    # Copy source files
    for src_file in source_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(source_dir)
            dest = tmp_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

    # Copy symbols into .docstar/symbols/
    docstar_symbols = tmp_path / ".docstar" / "symbols"
    for sym_file in symbols_dir.rglob("*.symbols.json"):
        rel = sym_file.relative_to(symbols_dir)
        dest = docstar_symbols / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sym_file, dest)

    return Config(root_path=tmp_path, respect_gitignore=False)


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_case_001_wrapper_pattern(tmp_path):
    """tools.py: wrapper functions alongside used constants must be detected as dead.

    Regression test from commit d9eaec6 where 5 of 7 identical dead functions
    were missed due to LLM batch bias from correctly-alive constants.
    """
    case_dir = FIXTURES_DIR / "dead_code" / "case_001_wrapper_pattern"
    expected = json.loads((case_dir / "expected.json").read_text())

    config = _setup_case_dir(tmp_path, case_dir)

    # Step 1: Run scan_references to get zero-ref candidates
    zero_refs, low_refs = scan_references(config)

    # All 7 dead functions should be zero-ref candidates
    zero_ref_names = {c.name for c in zero_refs}
    for dead_name in expected["dead"]:
        assert dead_name in zero_ref_names, (
            f"scan_references missed zero-ref candidate: {dead_name}"
        )

    # Step 2: Run LLM verification with real provider
    provider = create_provider("anthropic")
    try:
        # Filter to just the tools.py candidates (the file under test)
        tools_candidates = [
            c for c in zero_refs if c.source_path.endswith("tools.py")
        ]
        assert len(tools_candidates) > 0, "No tools.py candidates found"

        # Read the source file content
        tools_path = tmp_path / "src" / "docstar" / "tools.py"
        file_content = tools_path.read_text(errors="ignore")

        # Run verification in a single batch (mimics real audit behavior)
        verifications, _, _ = await _verify_batch_async(
            provider, config, tools_candidates,
            file_content, "", {},
        )

        # Build result lookup
        result_by_name = {v.name: v for v in verifications}

        # Step 3: Assert all expected dead symbols are marked dead
        for dead_name in expected["dead"]:
            if dead_name in result_by_name:
                assert result_by_name[dead_name].is_dead, (
                    f"Expected {dead_name} to be dead but LLM said alive: "
                    f"{result_by_name[dead_name].reason}"
                )

        # Step 4: Assert all expected alive symbols are marked alive
        for alive_name in expected["alive"]:
            if alive_name in result_by_name:
                assert not result_by_name[alive_name].is_dead, (
                    f"Expected {alive_name} to be alive but LLM said dead: "
                    f"{result_by_name[alive_name].reason}"
                )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_case_002_internal_dataclass(tmp_path):
    """audit.py: internal dataclasses used by externally-referenced functions must be alive.

    Regression test for false positives on AuditIssue and AuditResult — dataclasses
    with zero external references that are transitively alive through run_audit etc.
    """
    case_dir = FIXTURES_DIR / "dead_code" / "case_002_internal_dataclass"
    expected = json.loads((case_dir / "expected.json").read_text())

    config = _setup_case_dir(tmp_path, case_dir)

    # Step 1: Verify scanner-level transitive liveness filter
    zero_refs, low_refs = scan_references(config)
    zero_ref_names = {c.name for c in zero_refs}

    # AuditIssue and AuditResult should be filtered out by transitive liveness
    for alive_name in expected["alive"]:
        assert alive_name not in zero_ref_names, (
            f"Transitive liveness filter missed {alive_name} — "
            f"it should NOT be a zero-ref candidate"
        )

    # Step 2: Also verify LLM handles this correctly (belt-and-suspenders)
    # Manually create candidates as if the scanner filter didn't exist
    provider = create_provider("anthropic")
    try:
        audit_path = tmp_path / "src" / "docstar" / "audit.py"
        file_content = audit_path.read_text(errors="ignore")

        candidates = [
            DeadCodeCandidate(
                source_path="src/docstar/audit.py",
                name=name,
                kind="class",
                line_start={"AuditIssue": 19, "AuditResult": 32}[name],
                line_end={"AuditIssue": 30, "AuditResult": 50}[name],
                ref_count=0,
            )
            for name in expected["alive"]
        ]

        verifications, _, _ = await _verify_batch_async(
            provider, config, candidates,
            file_content, "", {},
        )

        result_by_name = {v.name: v for v in verifications}

        for alive_name in expected["alive"]:
            if alive_name in result_by_name:
                assert not result_by_name[alive_name].is_dead, (
                    f"Expected {alive_name} to be alive but LLM said dead: "
                    f"{result_by_name[alive_name].reason}"
                )

        for dead_name in expected["dead"]:
            if dead_name in result_by_name:
                assert result_by_name[dead_name].is_dead, (
                    f"Expected {dead_name} to be dead but LLM said alive: "
                    f"{result_by_name[dead_name].reason}"
                )
    finally:
        await provider.close()
