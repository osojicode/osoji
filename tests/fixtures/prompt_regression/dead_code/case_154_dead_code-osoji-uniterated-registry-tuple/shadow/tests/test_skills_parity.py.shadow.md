# tests\test_skills_parity.py
@source-hash: 56d28f4d13f8ceb2
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:26Z

## Purpose
Parity tests ensuring skill markdown files in `src/osoji/skills/` (canonical, shipped in wheel) remain byte-identical to their mirrors in `.claude/skills/<name>/SKILL.md` (Claude Code auto-discovery copies). Fails loudly on any drift to enforce dual-location consistency.

## Key Elements

### Constants
- `REPO_ROOT` (L13): `Path(__file__).parent.parent` — resolves to the repository root; used as the base for all file path construction.
- `MIRRORED_SKILLS` (L15): Tuple `("osoji-sweep", "osoji-triage")` — declares which skills are subject to parity enforcement. **Note:** not currently iterated programmatically; tests are written as individual functions.

### Functions
- `_assert_in_sync(name)` (L18–25): Internal helper. Reads bytes from both the canonical path (`src/osoji/skills/<name>.md`) and mirror path (`.claude/skills/<name>/SKILL.md`) and asserts byte-level equality. Raises `AssertionError` with a descriptive message on mismatch.
- `test_osoji_sweep_skill_in_sync()` (L28–29): pytest test for `"osoji-sweep"` skill parity.
- `test_osoji_triage_skill_in_sync()` (L32–33): pytest test for `"osoji-triage"` skill parity.

## Architecture / Design Decisions
- **Byte-level comparison** (`read_bytes()`) ensures no encoding normalization can mask differences — even whitespace or line-ending drift is caught.
- Skills are individually tested rather than parameterized, making test names unambiguous in CI output.
- `MIRRORED_SKILLS` tuple exists as a registry of mirrored skills but is not used to drive test generation; adding a new skill requires both adding to the tuple and writing a new test function manually.
- No external test fixtures or mocking — purely filesystem-based assertions relative to `REPO_ROOT`.

## Constraints / Invariants
- Both file paths must exist at test time; missing files will raise `FileNotFoundError` (not a custom assertion error).
- Canonical source is `src/osoji/skills/<name>.md`; mirror is `.claude/skills/<name>/SKILL.md`.
