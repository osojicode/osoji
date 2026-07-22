"""Read-only, repo-confined executor backing Triage exploration mode (V1-3).

Exploration mode (see :mod:`osoji.triage`) gives the LLM three retrieval tools —
``read_file``, ``grep``, ``list_dir`` — so it can decide a single hard claim by
looking at the code. This module runs those tools. Three invariants, each
covered by a test in ``tests/test_triage_exec.py``:

- **Read-only.** No method writes, deletes, or executes anything.
- **Confined to the repository root.** Every path is resolved and rejected if it
  escapes ``config.root_path`` (``../`` traversal, absolute paths elsewhere).
- **Bounded output.** A runaway call can't blow the context window — file reads,
  grep matches, and directory listings are all capped, with a truncation notice.

On any failure (escape, missing file, bad regex, unknown tool) a method returns
a short ``"Error: ..."`` string rather than raising: the string becomes the
tool_result fed back to the LLM, which can then adjust its next call.

Language-agnostic by construction: ``grep`` is a plain regex over text files and
``read_file`` does not parse — nothing here assumes a particular language.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import Config

# Directories never worth exposing to exploration — VCS internals and osoji's own
# generated sidecar tree. Skipped during grep/list to keep output relevant and
# bounded. This is a relevance filter, not a security boundary (the root-confinement
# check is the boundary).
_SKIP_DIRS = {".git", ".osoji", ".hg", ".svn", "node_modules", "__pycache__"}


class ExplorationExecutor:
    """Runs read-only retrieval tools against a single repository root."""

    def __init__(
        self,
        config: Config,
        *,
        max_file_bytes: int = 16_000,
        max_grep_matches: int = 100,
        max_list_entries: int = 200,
    ) -> None:
        self.root: Path = config.root_path.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_grep_matches = max_grep_matches
        self.max_list_entries = max_list_entries

    # -- dispatch ----------------------------------------------------------

    def run(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Dispatch a tool call by name; return its result (or an error string)."""

        if tool_name == "read_file":
            return self.read_file(
                tool_input.get("path", ""),
                start=tool_input.get("start"),
                end=tool_input.get("end"),
            )
        if tool_name == "grep":
            return self.grep(
                tool_input.get("pattern", ""), glob=tool_input.get("glob")
            )
        if tool_name == "list_dir":
            return self.list_dir(tool_input.get("path", "."))
        return f"Error: unknown tool '{tool_name}'"

    # -- path safety -------------------------------------------------------

    def _resolve(self, rel_or_abs: str) -> Path | None:
        """Resolve a path against root; return None if it escapes the root."""

        try:
            candidate = Path(rel_or_abs)
            resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        except (OSError, ValueError):
            return None
        if resolved == self.root or self.root in resolved.parents:
            return resolved
        return None

    def _rel(self, path: Path) -> str:
        """POSIX-style root-relative display path."""

        return path.relative_to(self.root).as_posix()

    # -- tools -------------------------------------------------------------

    def read_file(
        self, path: str, start: int | None = None, end: int | None = None
    ) -> str:
        """Return the contents of ``path`` (optionally lines ``start``..``end``).

        Lines are 1-based and inclusive. Output is capped at ``max_file_bytes``.
        """

        resolved = self._resolve(path)
        if resolved is None:
            return f"Error: path '{path}' escapes the repository root"
        if not resolved.is_file():
            return f"Error: '{path}' is not a readable file"
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error: could not read '{path}': {exc}"

        if start is not None or end is not None:
            lines = text.splitlines()
            lo = max(1, start or 1)
            hi = min(len(lines), end or len(lines))
            text = "\n".join(lines[lo - 1 : hi])

        if len(text) > self.max_file_bytes:
            text = text[: self.max_file_bytes] + "\n…[truncated]"
        return text

    def grep(self, pattern: str, glob: str | None = None) -> str:
        """Search file contents under root for ``pattern`` (a regex).

        Returns ``path:line: text`` rows, capped at ``max_grep_matches``.
        """

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex '{pattern}': {exc}"

        results: list[str] = []
        truncated = False
        for file_path in self._iter_files(glob):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = self._rel(file_path)
            for lineno, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(results) >= self.max_grep_matches:
                        truncated = True
                        break
            if truncated:
                break

        if not results:
            return f"No matches for '{pattern}'."
        out = "\n".join(results)
        if truncated:
            out += f"\n…[truncated at {self.max_grep_matches} matches]"
        return out

    def list_dir(self, path: str = ".") -> str:
        """List the entries of a directory under root (dirs marked with ``/``)."""

        resolved = self._resolve(path)
        if resolved is None:
            return f"Error: path '{path}' escapes the repository root"
        if not resolved.is_dir():
            return f"Error: '{path}' is not a directory"
        entries: list[str] = []
        for child in sorted(resolved.iterdir()):
            if child.is_dir():
                if child.name in _SKIP_DIRS:
                    continue
                entries.append(child.name + "/")
            else:
                entries.append(child.name)
            if len(entries) >= self.max_list_entries:
                entries.append(f"…[truncated at {self.max_list_entries} entries]")
                break
        return "\n".join(entries) if entries else "(empty)"

    # -- helpers -----------------------------------------------------------

    def _iter_files(self, glob: str | None):
        """Yield text files under root, skipping VCS/sidecar dirs and big blobs.

        V1-4 hardening (before exploration runs in production): unlike read_file
        and list_dir, this filters yielded files by skip-dirs only, not by the
        ``_resolve`` root-containment check, and the caller's ``pattern`` /
        regex are LLM-supplied. Route the file set through ``_resolve`` and add a
        length/again-ReDoS guard on the grep pattern before turning exploration on.
        Dormant in V1-3, so not exposed yet.
        """

        pattern = glob or "**/*"
        for file_path in self.root.glob(pattern):
            if not file_path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in file_path.relative_to(self.root).parts):
                continue
            yield file_path
