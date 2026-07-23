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

# sha256 of TRIAGE_SYSTEM_PROMPT. A deliberate rubric change must update this
# hash in the same PR and carry its A/B evidence (wiki decisions/0022).
# History: 16b45f61… at the work#66 sectioning refactor; 67141f55… at the
# work#78/work#79 change; 19190bee… added the decisions/0025 latent_bug
# gap_type split; current hash re-founds the contract taxonomy on authority
# source (project_named/project_implicit/ecosystem/coincidental), renaming the
# `contract_literal_classes` section to `contract_classes` (ratified 2026-07-22).
FROZEN_SHA = "ed0458522786c896578581b876eab55b9c8ebfca213fc10e1385c1861532b491"


def test_assembled_prompt_is_byte_identical() -> None:
    sha = hashlib.sha256(TRIAGE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert sha == FROZEN_SHA


def test_full_render_matches_constant() -> None:
    assert render_triage_prompt() == TRIAGE_SYSTEM_PROMPT


def test_sections_are_nonempty() -> None:
    assert len(TRIAGE_PROMPT_SECTIONS) == 16
    for name, text in TRIAGE_PROMPT_SECTIONS.items():
        assert text, f"empty section: {name}"


def test_contract_section_renamed_to_authority_taxonomy() -> None:
    # The literal-specific section key is retired; the authority-source rewrite
    # carries the de-literalized name (ratified 2026-07-22).
    assert "contract_classes" in TRIAGE_PROMPT_SECTIONS
    assert "contract_literal_classes" not in TRIAGE_PROMPT_SECTIONS


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
