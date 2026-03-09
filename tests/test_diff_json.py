"""Tests for diff JSON formatting."""

import json

from osoji.diff import DiffImpactReport, format_diff_json


def test_format_diff_json_includes_config_snapshot():
    report = DiffImpactReport(
        base_ref="main",
        changed_source=[],
        changed_docs=[],
        stale_shadows=[],
        doc_references=[],
        config_snapshot={
            "resolution_order": ["cli", "env", "project", "global", "builtin"],
            "provider": {"value": "openai", "source": "project", "trace": []},
            "models": {
                "small": {"value": "gpt-5-mini", "source": "global", "trace": []},
                "medium": {"value": "gpt-5.2", "source": "project", "trace": []},
                "large": {"value": "gpt-5.4", "source": "project", "trace": []},
            },
        },
    )

    payload = json.loads(format_diff_json(report))

    assert payload["config"]["provider"]["value"] == "openai"
    assert payload["config"]["models"]["medium"]["value"] == "gpt-5.2"
