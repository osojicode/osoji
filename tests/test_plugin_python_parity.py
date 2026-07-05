"""Golden-file parity harness for the Python plugin (V1-6a).

The committed golden (`tests/goldens/python_facts.json`) freezes the exact
``extract_project_facts`` output of the pre-tree-sitter ``ast`` plugin over a
purpose-built corpus (`tests/fixtures/python_parity/project/`). The active
``PythonPlugin`` must reproduce it bit-identically — this is the migration's
behavior contract, and it stays after the legacy plugin is deleted.

Regenerate (only when deliberately changing extraction behavior):
    OSOJI_REGEN_GOLDENS=1 pytest tests/test_plugin_python_parity.py

The corpus files are frozen — do not edit them, add new files instead (and
regenerate the golden in the same commit with an explanation).
"""

import json
import os
from pathlib import Path

from osoji.plugins.python_plugin import PythonPlugin

CORPUS = Path(__file__).parent / "fixtures" / "python_parity" / "project"
GOLDEN = Path(__file__).parent / "goldens" / "python_facts.json"


def _extract(plugin) -> dict:
    files = sorted(
        p for p in CORPUS.rglob("*") if p.suffix in (".py", ".pyi")
    )
    facts = plugin.extract_project_facts(CORPUS, files)
    return {
        rel: {
            "imports": ef.imports,
            "exports": ef.exports,
            "calls": ef.calls,
            "member_writes": ef.member_writes,
            "string_literals": ef.string_literals,
        }
        for rel, ef in sorted(facts.items())
    }


def test_corpus_is_present():
    assert (CORPUS / "pkg" / "core.py").is_file()
    assert (CORPUS / "broken" / "syntax_error.py").is_file()


def test_golden_parity():
    actual = _extract(PythonPlugin())

    if os.environ.get("OSOJI_REGEN_GOLDENS") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(actual, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected


def test_syntax_error_file_is_absent_from_output():
    actual = _extract(PythonPlugin())

    assert "broken/syntax_error.py" not in actual
    assert "broken/bad_bytes.py" in actual  # errors=replace keeps it parseable
