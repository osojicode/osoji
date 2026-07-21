"""Sectioning guard for the triage rubric (work#66, wiki decisions/0022).

The rubric is assembled from named sections so ablation variants and
per-section optimization can target them. Assembly must be byte-identical to
the pre-sectioning literal: an accidental edit to any section is a rubric
change, and rubric changes go through a corpus-replay A/B, not a refactor.
"""

import hashlib

import pytest

from osoji.triage import (
    TRIAGE_PROMPT_SECTIONS,
    TRIAGE_SYSTEM_PROMPT,
    render_triage_prompt,
)

# sha256 of TRIAGE_SYSTEM_PROMPT at the work#66 sectioning refactor. A
# deliberate rubric change must update this hash in the same PR and carry its
# A/B evidence (wiki decisions/0022).
FROZEN_SHA = "16b45f611fc84fb76d60d8bc9ec0ce0c0f65af93c8d2d137014554a4354ed4da"


def test_assembled_prompt_is_byte_identical() -> None:
    sha = hashlib.sha256(TRIAGE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert sha == FROZEN_SHA


def test_full_render_matches_constant() -> None:
    assert render_triage_prompt() == TRIAGE_SYSTEM_PROMPT


def test_sections_are_nonempty() -> None:
    assert len(TRIAGE_PROMPT_SECTIONS) == 15
    for name, text in TRIAGE_PROMPT_SECTIONS.items():
        assert text, f"empty section: {name}"


@pytest.mark.parametrize("name", list(TRIAGE_PROMPT_SECTIONS))
def test_omit_removes_exactly_that_section(name: str) -> None:
    expected = "".join(
        text for key, text in TRIAGE_PROMPT_SECTIONS.items() if key != name
    )
    assert render_triage_prompt(omit=[name]) == expected
    assert render_triage_prompt(omit=[name]) != TRIAGE_SYSTEM_PROMPT


def test_unknown_section_raises() -> None:
    with pytest.raises(ValueError, match="no_such_section"):
        render_triage_prompt(omit=["no_such_section"])
