"""Mechanical claim extraction from markdown (Tier A of decisions/0031).

Only literal, checkable claims are extracted here: a script a doc tells the
reader to run, a repo-relative path a doc names. Anything that reads as a
placeholder, URL, absolute path, glob or shell expansion is not a claim.
Prose claims that need judgement (behaviour, signatures, counts) are Tier B
and are not this module's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `npm run x`, `pnpm run x`, `yarn run x`, `pnpm x`, `yarn x`, `npm test|start`
_SCRIPT_RE = re.compile(
    r"\b(?P<pm>npm|pnpm|yarn)\s+(?:run\s+(?P<run>[\w:.\-]+)|(?P<bare>[\w:.\-]+))"
)
_MAKE_RE = re.compile(r"\bmake\s+(?P<target>[A-Za-z_][\w.\-]*)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)\s*(\S*)")
# `[label](target)` -- an inline markdown link. The target is everything up
# to whitespace (a link title, if any, follows a space) or the closing paren.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
# A bare, unquoted whitespace-delimited token on a fenced command line --
# the same shape a backtick span already looks for, applied to code that
# marks itself as a command without also quoting the path in backticks.
_FENCE_TOKEN_RE = re.compile(r"\S+")
# Fence languages that are shell transcripts, where a bare argument is a
# command the reader is told to run -- not a language whose own syntax
# (an object literal, a JSON value, a type signature) would otherwise be
# misread as a path argument.
_SHELL_FENCE_LANGS = {"bash", "sh", "shell", "zsh", "console", "cmd", "bat", "powershell", "ps1"}

# Package-manager verbs that are never project scripts. Principle: a bare
# `pm <word>` is a script claim only when the word is not a verb the package
# manager itself defines; npm's `test`/`start` are script aliases.
_PM_BUILTINS = {
    "install", "i", "ci", "add", "remove", "rm", "uninstall", "update", "upgrade",
    "link", "unlink", "publish", "pack", "init", "exec", "dlx", "create", "cache",
    "config", "audit", "outdated", "why", "ls", "list", "info", "view", "login",
    "logout", "whoami", "version", "help", "run", "workspace", "workspaces", "dedupe",
    "prune", "rebuild", "store", "setup", "import", "patch", "fetch", "env", "up",
}
_NPM_SCRIPT_ALIASES = {"test", "start", "stop", "restart"}

_PLACEHOLDER_SEGMENTS = {"path", "to", "your", "my", "some", "example", "foo", "bar"}


@dataclass(frozen=True)
class DocClaim:
    kind: str                # "script_exists" | "path_exists"
    name: str                # the script name or normalized relative path
    doc_path: str
    line: int                # 1-based
    text: str                # the literal token as written
    ecosystem: str | None    # "npm" | "make" | None
    in_fence: bool


def is_placeholder(token: str) -> bool:
    if any(ch in token for ch in "<>{}$*"):
        return True
    if "..." in token:
        return True
    segments = [s.lower() for s in token.replace("\\", "/").split("/")]
    return any(seg in _PLACEHOLDER_SEGMENTS for seg in segments)


def _looks_like_repo_path(token: str) -> bool:
    t = token.strip()
    if not t or is_placeholder(t):
        return False
    # A leading `@` marks a package scope/handle in every ecosystem (npm,
    # several Python/Go tools) -- never a relative repo path, same principle
    # as the `~` (home dir) exclusion below.
    if "://" in t or t.startswith(("/", "~", "\\", "@")) or re.match(r"^[A-Za-z]:[\\/]", t):
        return False
    if t.startswith("-") or " " in t:
        return False
    # `KEY=value` (an env-var assignment) or `--flag=value` is a name/value
    # pair, not a path argument, even when the value side contains a "/" --
    # same principle as excluding a bare `-`-prefixed flag.
    if "=" in t:
        return False
    # A separator is required. Bare `name.ext` tokens are ambiguous with dotted
    # identifiers (`process.env`, `Client.close`) and would produce false
    # "nonexistent path" findings; they are left to a later, registry-aware
    # extraction. Losing `README.md`-style bare claims costs little recall.
    return "/" in t


def _norm_path(token: str) -> str:
    s = token.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    # A doc that names `src/a.ts:42` or `docs/guide.md#usage` is still making
    # a claim about the file, not about a token that happens to include the
    # line/anchor suffix — strip the suffix so the claim's `name` matches the
    # registry entry. `text` (the literal token as written) is left alone.
    # Suffix-stripping runs before the trailing-slash strip so a trailing
    # slash left behind by an anchor (`docs/architecture/#overview`) is
    # still removed.
    s = re.sub(r":\d+(-\d+)?$", "", s)
    s = re.sub(r"#[^/]*$", "", s)
    return s.rstrip("/")


def extract_doc_claims(doc_path: str, content: str) -> list[DocClaim]:
    claims: list[DocClaim] = []
    seen: set[tuple[str, str, int]] = set()
    in_fence = False
    fence_lang = ""

    def add(kind: str, name: str, line: int, text: str, eco: str | None) -> None:
        key = (kind, name, line)
        if key in seen:
            return
        seen.add(key)
        claims.append(DocClaim(kind, name, doc_path, line, text, eco, in_fence))

    for i, raw in enumerate(content.splitlines(), start=1):
        fence_m = _FENCE_RE.match(raw)
        if fence_m:
            in_fence = not in_fence
            fence_lang = fence_m.group(2).lower() if in_fence else ""
            continue

        # A command is "a script a doc tells the reader to run" — that's a
        # fenced code line, or a backtick span in prose. Ordinary prose
        # ("make sure", "pnpm monorepo") is never scanned for commands; only
        # what the doc marks as code is.
        command_sources = [raw] if in_fence else [m.group(1) for m in _BACKTICK_RE.finditer(raw)]
        for source in command_sources:
            for m in _SCRIPT_RE.finditer(source):
                name = m.group("run") or m.group("bare")
                # A `-`-prefixed bare token right after the package manager
                # (`pnpm --filter x`) is a CLI flag, never a script name --
                # true in every package manager, not just npm.
                if m.group("bare") and name.startswith("-"):
                    continue
                if m.group("bare") and (name in _PM_BUILTINS or (m.group("pm") == "npm" and name not in _NPM_SCRIPT_ALIASES)):
                    continue
                if name in _PM_BUILTINS:
                    continue
                add("script_exists", name, i, name, "npm")
            for m in _MAKE_RE.finditer(source):
                add("script_exists", m.group("target"), i, m.group("target"), "make")

        for m in _BACKTICK_RE.finditer(raw):
            token = m.group(1).strip()
            if _SCRIPT_RE.search(token) or _MAKE_RE.search(token):
                continue  # already handled as a command
            if _looks_like_repo_path(token):
                add("path_exists", _norm_path(token), i, token, None)

        if in_fence:
            if fence_lang in _SHELL_FENCE_LANGS:
                # A fenced command line marks its whole content as code the
                # same way a backtick span marks a prose token as code -- a
                # bare (unquoted) argument here is as much a literal claim as
                # a backticked one, just without the extra punctuation.
                # Scoped to shell-transcript languages: an undeclared fence
                # is as likely to be an ASCII directory tree as a command,
                # and a typed-language fence (`typescript`, `json`) has its
                # own token grammar that reads nothing like a shell argument.
                for tok_m in _FENCE_TOKEN_RE.finditer(raw):
                    token = tok_m.group(0).strip("\"'(),;")
                    if _SCRIPT_RE.search(token) or _MAKE_RE.search(token):
                        continue  # already handled as a command
                    if _looks_like_repo_path(token):
                        add("path_exists", _norm_path(token), i, token, None)
        else:
            # A markdown link target is a claim about where the file lives,
            # the same as a backticked path -- just wrapped in `[label](...)`
            # instead of backticks. Only scanned in prose: fenced code has
            # its own syntax (e.g. array literals) that can coincidentally
            # look like `[...](...)`. URLs and in-page anchors are excluded
            # by the same repo-path heuristic and an explicit anchor check.
            for m in _MD_LINK_RE.finditer(raw):
                target = m.group(1).strip()
                if target.startswith("#"):
                    continue
                if _looks_like_repo_path(target):
                    add("path_exists", _norm_path(target), i, target, None)
    return claims
