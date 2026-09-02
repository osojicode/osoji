import importlib.util
from pathlib import Path

from osoji.claims_docs import DocClaim
from osoji.tier_a import EvidencePacket

_spec = importlib.util.spec_from_file_location("tier_a_replay", Path("scripts/tier_a_replay.py"))
tier_a_replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier_a_replay)


def _packet(doc, name, verdict="contradicted"):
    claim = DocClaim("script_exists", name, doc, 3, name, "npm", False)
    return EvidencePacket(claim=claim, verdict=verdict, namespace="scripts")


def test_score_rows_matches_contradicted_packet_on_same_doc_by_name():
    rows = [
        {"path": "docs/testing-guide.md", "kind": "nonexistent_artifact", "claim": "Old: run `npm run test:ui` — no such script"},
        {"path": "docs/testing-guide.md", "kind": "wrong_path", "claim": "Old: `tests/core/unit/server/server.test.ts` was deleted"},
        {"path": "README.md", "kind": "nonexistent_artifact", "claim": "Old: `registerTools()` does not exist"},
    ]
    packets = [_packet("docs/testing-guide.md", "test:ui"), _packet("README.md", "test:ui", verdict="supported")]
    scored = tier_a_replay.score_rows(rows, packets)
    assert [r["hit"] for r in scored] == [True, False, False]
    assert scored[0]["matched"] == "test:ui"
