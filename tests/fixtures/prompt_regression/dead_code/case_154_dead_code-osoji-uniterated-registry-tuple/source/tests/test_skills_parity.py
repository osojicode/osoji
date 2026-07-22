"""Parity tests for skills mirrored between src/osoji/skills/ and .claude/skills/.

`src/osoji/skills/<name>.md` is the canonical source — it ships in the wheel
and is what `osoji skills list|show` reads. `.claude/skills/<name>/SKILL.md`
is a copy that Claude Code auto-discovers when working on this repo.

These tests fail loudly on drift so updating one location forces updating the
other.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

MIRRORED_SKILLS = ("osoji-sweep", "osoji-triage")


def _assert_in_sync(name: str) -> None:
    canonical = (REPO_ROOT / "src" / "osoji" / "skills" / f"{name}.md").read_bytes()
    mirror = (REPO_ROOT / ".claude" / "skills" / name / "SKILL.md").read_bytes()
    assert canonical == mirror, (
        f"{name} skill drift: src/osoji/skills/{name}.md and "
        f".claude/skills/{name}/SKILL.md must be byte-identical. "
        "Update both when changing either."
    )


def test_osoji_sweep_skill_in_sync() -> None:
    _assert_in_sync("osoji-sweep")


def test_osoji_triage_skill_in_sync() -> None:
    _assert_in_sync("osoji-triage")
