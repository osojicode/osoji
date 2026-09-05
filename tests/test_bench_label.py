"""Tests for the benchmark row labeler (bench Phase 0.1, wiki specs/0005).

An LLM reader labels each mined row: partition (was the parent text wrong?),
domain (what its truth depends on, decisions/0029), kind (the PR #643
taxonomy) and claim shape (what the claim asserts: path, script, symbol,
behaviour, ...). The labeler is resumable and records one label per reader
so a panel can be built from repeated runs.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from bench.label import (  # noqa: E402
    CLAIM_SHAPES,
    KINDS,
    LABEL_TOOL,
    PARTITIONS,
    build_messages,
    label_rows,
    validate_label,
)
from osoji.config import Config  # noqa: E402
from osoji.llm.types import CompletionResult, ToolCall  # noqa: E402


def _row(n: int = 1) -> dict:
    return {
        "row_id": f"fixture:abc123def0:{n}", "repo": "fixture", "commit": "abc123def0" + "0" * 30,
        "parent": "1" * 40, "commit_date": "2026-01-01T00:00:00Z", "subject": "fix README port",
        "path": "README.md", "renamed_to": None, "old_start": 3, "old_len": 1,
        "new_start": 3, "new_len": 1, "hunk_count": 1, "hunk_seqs": [1], "old_starts": [3],
        "minus_text": ["Run `python app.py --port 8000`."],
        "plus_text": ["Run `python app.py --port 8080`."],
        "context_before": ["# App", ""], "context_after": ["", "See docs/guide.md."],
        "minus_lines": 1, "plus_lines": 1, "labels": None,
    }


_GOOD = {
    "partition": "correction", "domain": "checkout", "kind": "false_statement",
    "claim_shape": "value", "claim": "The README says the default port is 8000; it is 8080.",
    "evidence_path": "src/app.py", "reasoning": "default changed", "confidence": 0.9,
}


class FakeProvider:
    def __init__(self, inputs=None, error=None):
        self.calls = 0
        self._inputs = list(inputs or [])
        self._error = error

    async def complete(self, messages, system, options):
        self.calls += 1
        if self._error is not None:
            raise self._error
        data = self._inputs.pop(0) if self._inputs else dict(_GOOD)
        return CompletionResult(
            content=None,
            tool_calls=[ToolCall(id=f"t{self.calls}", name=LABEL_TOOL.name, input=data)],
            input_tokens=50, output_tokens=20, model="test", stop_reason="tool_use",
        )

    async def close(self):
        pass


class TestTaxonomy:
    def test_every_closed_set_has_an_other_outlet(self):
        assert "other" in PARTITIONS and "other" in KINDS and "other" in CLAIM_SHAPES

    def test_tool_schema_enumerates_the_taxonomy(self):
        props = LABEL_TOOL.input_schema["properties"]
        assert props["partition"]["enum"] == list(PARTITIONS)
        assert props["kind"]["enum"] == list(KINDS)
        assert props["claim_shape"]["enum"] == list(CLAIM_SHAPES)
        assert set(LABEL_TOOL.input_schema["required"]) >= {"partition", "claim", "claim_shape"}


class TestBuildMessages:
    def test_user_message_carries_diff_and_context(self):
        system, user = build_messages(_row())
        assert "README.md" in user and "fix README port" in user
        assert "-Run `python app.py --port 8000`." in user
        assert "+Run `python app.py --port 8080`." in user
        assert "See docs/guide.md." in user
        assert "3" in user  # old-side line number

    def test_system_states_principles_not_catalogs(self):
        system, _ = build_messages(_row())
        assert "checkout" in system and "world" in system and "runtime" in system
        assert "correction" in system and "restructure" in system
        assert "claim_shape" in system or "claim shape" in system


class TestValidateLabel:
    def test_unknown_enum_values_route_to_other(self):
        data = {**_GOOD, "kind": "weird_kind", "claim_shape": "??", "partition": "novel"}
        label = validate_label(data)
        assert label["kind"] == "other"
        assert label["claim_shape"] == "other"
        assert label["partition"] == "other"

    def test_unknown_domain_becomes_none(self):
        assert validate_label({**_GOOD, "domain": "elsewhere"})["domain"] is None

    def test_missing_claim_is_rejected(self):
        with pytest.raises(ValueError):
            validate_label({k: v for k, v in _GOOD.items() if k != "claim"})

    def test_confidence_is_clamped(self):
        assert validate_label({**_GOOD, "confidence": 7})["confidence"] == 1.0


class TestLabelRows:
    def test_writes_labels_per_reader_and_resumes(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
        out = temp_dir / "rows.labeled.jsonl"
        rows = [_row(1), _row(2)]
        provider = FakeProvider()

        summary = asyncio.run(label_rows(rows, provider, config, model="m", reader="r1", out_path=out))

        assert provider.calls == 2
        assert summary["labeled"] == 2 and summary["failed"] == 0
        written = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert [w["row_id"] for w in written] == [r["row_id"] for r in rows]
        assert written[0]["labels"]["r1"]["kind"] == "false_statement"
        assert written[0]["labels"]["r1"]["model"] == "m"

        erroring = FakeProvider(error=RuntimeError("must not be called"))
        summary2 = asyncio.run(label_rows(rows, erroring, config, model="m", reader="r1", out_path=out))
        assert erroring.calls == 0
        assert summary2["skipped"] == 2

    def test_second_reader_adds_a_label_without_clobbering(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
        out = temp_dir / "rows.labeled.jsonl"
        rows = [_row(1)]
        asyncio.run(label_rows(rows, FakeProvider(), config, model="m", reader="r1", out_path=out))
        asyncio.run(label_rows(rows, FakeProvider([{**_GOOD, "kind": "wrong_count"}]), config,
                               model="m2", reader="r2", out_path=out))

        (written,) = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert set(written["labels"]) == {"r1", "r2"}
        assert written["labels"]["r2"]["kind"] == "wrong_count"

    def test_failure_is_recorded_and_does_not_stop_the_batch(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False, quiet=True)
        out = temp_dir / "rows.labeled.jsonl"
        rows = [_row(1), _row(2)]
        provider = FakeProvider(inputs=[{"partition": "correction"}, dict(_GOOD)])  # first lacks claim

        summary = asyncio.run(label_rows(rows, provider, config, model="m", reader="r1", out_path=out))

        assert summary["failed"] == 1 and summary["labeled"] == 1
        written = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert written[0]["labels"] is None or "r1" not in (written[0]["labels"] or {})
        assert written[1]["labels"]["r1"]["kind"] == "false_statement"
