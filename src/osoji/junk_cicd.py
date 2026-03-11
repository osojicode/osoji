"""Dead CI/CD detection via pipeline file parsing and path reference checking."""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .async_utils import gather_with_buffer
from .config import ANTHROPIC_MODEL_SMALL, Config
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult
from .llm.base import LLMProvider
from .llm.runtime import create_runtime
from .llm.types import Message, MessageRole, CompletionOptions
from .tools import get_dead_cicd_tool_definitions, get_extract_cicd_elements_tool_definitions
from .walker import list_repo_files



@dataclass
class CICDElement:
    """A parsed element from a CI/CD file."""

    cicd_file: str            # e.g. ".github/workflows/ci.yml"
    element_type: str         # "workflow_job", "makefile_target", "gitlab_job"
    element_name: str
    line_start: int
    line_end: int
    referenced_paths: list[str] = field(default_factory=list)
    referenced_commands: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)


@dataclass
class CICDCandidate:
    """A CI/CD element that may be dead."""

    cicd_file: str
    element_name: str
    element_type: str
    line_start: int
    line_end: int
    missing_paths: list[str]
    element_content: str      # raw text of the element for LLM context
    full_file_content: str


@dataclass
class CICDVerification:
    """Result of verifying whether a CI/CD element is dead."""

    cicd_file: str
    element_name: str
    element_type: str
    line_start: int
    line_end: int
    is_dead: bool
    confidence: float
    reason: str
    remediation: str


# --- CI/CD file discovery ---

def discover_cicd_files(config: Config) -> list[tuple[Path, str]]:
    """Discover CI/CD configuration files via direct filesystem scan.

    .github is in DEFAULT_IGNORE_PATTERNS, so we use Path.iterdir()
    instead of list_repo_files().

    Returns list of (absolute_path, cicd_type).
    """
    root = config.root_path
    found: list[tuple[Path, str]] = []

    # .github/workflows/*.yml and *.yaml
    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for child in workflows_dir.iterdir():
            if child.is_file() and child.suffix in (".yml", ".yaml"):
                found.append((child, "github_workflow"))

    # Makefile variants
    for name in ("Makefile", "GNUmakefile", "makefile"):
        p = root / name
        if p.is_file():
            found.append((p, "makefile"))

    # GitLab CI
    p = root / ".gitlab-ci.yml"
    if p.is_file():
        found.append((p, "gitlab_ci"))

    # Jenkinsfile
    p = root / "Jenkinsfile"
    if p.is_file():
        found.append((p, "jenkinsfile"))

    # CircleCI
    p = root / ".circleci" / "config.yml"
    if p.is_file():
        found.append((p, "circleci"))

    # Azure Pipelines
    p = root / "azure-pipelines.yml"
    if p.is_file():
        found.append((p, "azure_pipelines"))

    # Travis CI
    p = root / ".travis.yml"
    if p.is_file():
        found.append((p, "travis_ci"))

    return found


# --- CI/CD parsers ---

def _parse_github_workflow(content: str, path: str) -> list[CICDElement]:
    """Parse a GitHub Actions workflow file.

    Regex-based extraction of jobs and their run/uses steps.
    """
    elements: list[CICDElement] = []
    lines = content.splitlines()

    # Find jobs: section
    jobs_line = None
    for i, line in enumerate(lines):
        if re.match(r"^jobs:\s*$", line):
            jobs_line = i
            break

    if jobs_line is None:
        return []

    # Extract job names: lines at exactly 2 spaces of indent after jobs:
    job_re = re.compile(r"^  ([a-zA-Z_][\w-]*):\s*$")
    jobs: list[tuple[str, int, int]] = []  # (name, start, end)

    for i in range(jobs_line + 1, len(lines)):
        m = job_re.match(lines[i])
        if m:
            if jobs:
                jobs[-1] = (jobs[-1][0], jobs[-1][1], i - 1)
            jobs.append((m.group(1), i, len(lines) - 1))
        # If we hit a line at indent 0 that isn't empty/comment, jobs section is over
        elif lines[i].strip() and not lines[i].startswith(" ") and not lines[i].startswith("#"):
            if jobs:
                jobs[-1] = (jobs[-1][0], jobs[-1][1], i - 1)
            break

    for job_name, start, end in jobs:
        job_lines = lines[start:end + 1]

        # Extract referenced paths and commands from run: and uses: lines
        paths: list[str] = []
        commands: list[str] = []

        in_run_block = False
        run_block_indent = 0
        for jline in job_lines:
            stripped = jline.strip()

            # Handle "- run:" or "run:" (with or without list marker)
            run_match = re.match(r"^-?\s*run:\s*(.*)", stripped)
            if run_match:
                rest = run_match.group(1).strip().strip("|")
                if rest:
                    commands.append(rest)
                    paths.extend(_extract_paths_from_command(rest))
                    in_run_block = False
                else:
                    in_run_block = True
                    # Determine indent level of the run: line
                    run_block_indent = len(jline) - len(jline.lstrip())
                continue

            if in_run_block:
                line_indent = len(jline) - len(jline.lstrip())
                if stripped and line_indent > run_block_indent:
                    commands.append(stripped)
                    paths.extend(_extract_paths_from_command(stripped))
                elif not stripped:
                    continue
                else:
                    in_run_block = False

            # Handle "- uses:" or "uses:"
            uses_match = re.match(r"^-?\s*uses:\s*(.*)", stripped)
            if uses_match:
                commands.append(uses_match.group(1).strip())

        elements.append(CICDElement(
            cicd_file=path,
            element_type="workflow_job",
            element_name=job_name,
            line_start=start + 1,  # 1-indexed
            line_end=end + 1,
            referenced_paths=paths,
            referenced_commands=commands,
        ))

    return elements


def _parse_makefile(content: str, path: str) -> list[CICDElement]:
    """Parse a Makefile to extract targets and recipe commands."""
    elements: list[CICDElement] = []
    lines = content.splitlines()

    target_re = re.compile(r"^([a-zA-Z_][\w.\-]*)(?:\s+[a-zA-Z_][\w.\-]*)?\s*:(?!=)")
    current_target: str | None = None
    current_start = 0
    current_paths: list[str] = []
    current_commands: list[str] = []

    def _flush():
        if current_target is not None:
            elements.append(CICDElement(
                cicd_file=path,
                element_type="makefile_target",
                element_name=current_target,
                line_start=current_start + 1,
                line_end=len(lines),
                referenced_paths=current_paths[:],
                referenced_commands=current_commands[:],
            ))

    for i, line in enumerate(lines):
        m = target_re.match(line)
        if m:
            _flush()
            current_target = m.group(1)
            current_start = i
            current_paths = []
            current_commands = []
            # Update end of previous element
            if elements:
                elements[-1].line_end = i
        elif line.startswith("\t") and current_target is not None:
            cmd = line[1:].strip()
            if cmd and not cmd.startswith("#"):
                current_commands.append(cmd)
                current_paths.extend(_extract_paths_from_command(cmd))

    _flush()

    return elements


def _parse_gitlab_ci(content: str, path: str) -> list[CICDElement]:
    """Parse a GitLab CI file to extract jobs."""
    elements: list[CICDElement] = []
    lines = content.splitlines()

    reserved_keys = {
        "stages", "variables", "default", "include", "image", "services",
        "before_script", "after_script", "cache", "workflow",
        "pages", "trigger", "resource_group", "retry", "timeout",
        "interruptible", "artifacts", "dependencies", "needs",
        "environment", "release", "coverage", "parallel", "tags",
        "only", "except", "rules", "when", "allow_failure",
    }

    # Find top-level keys (not indented)
    job_re = re.compile(r"^([a-zA-Z_][\w.\-/]*):\s*")
    jobs: list[tuple[str, int]] = []

    for i, line in enumerate(lines):
        m = job_re.match(line)
        if m:
            key = m.group(1)
            if key.startswith(".") or key in reserved_keys:
                continue
            jobs.append((key, i))

    for idx, (job_name, start) in enumerate(jobs):
        end = jobs[idx + 1][1] - 1 if idx + 1 < len(jobs) else len(lines) - 1
        job_lines = lines[start:end + 1]

        paths: list[str] = []
        commands: list[str] = []
        in_script = False

        for jline in job_lines:
            stripped = jline.strip()
            if stripped.startswith("script:"):
                in_script = True
                continue
            if in_script:
                if stripped.startswith("- "):
                    cmd = stripped[2:].strip()
                    commands.append(cmd)
                    paths.extend(_extract_paths_from_command(cmd))
                elif stripped and not stripped.startswith("#") and not jline.startswith("  "):
                    in_script = False

        elements.append(CICDElement(
            cicd_file=path,
            element_type="gitlab_job",
            element_name=job_name,
            line_start=start + 1,
            line_end=end + 1,
            referenced_paths=paths,
            referenced_commands=commands,
        ))

    return elements


_EXTRACT_CICD_SYSTEM_PROMPT = """You are a CI/CD configuration parser. Extract all discrete pipeline elements from the given configuration file.

For each element (job, stage, target, step, pipeline), identify:
1. Its name and type
2. The line range it occupies in the file
3. Any file paths it references (scripts, directories, config files)
4. Any commands it runs

Be thorough — extract ALL elements. For line numbers, count from line 1."""


async def _parse_cicd_via_haiku(
    provider: LLMProvider,
    content: str,
    path: str,
    cicd_type: str,
    config: Config | None = None,
) -> tuple[list[CICDElement], int, int]:
    """Parse a CI/CD file using Haiku when no regex parser is available.

    Returns (elements, input_tokens, output_tokens).
    """
    lines = [
        f"## CI/CD file: `{path}` (type: {cicd_type})\n",
        f"```\n{content[:50000]}\n```\n",
        "Extract ALL pipeline elements from this file.",
    ]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
        system=_EXTRACT_CICD_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("small") if config is not None else ANTHROPIC_MODEL_SMALL,
            max_tokens=4096,
            reservation_key="junk_cicd.extract_elements",
            tools=get_extract_cicd_elements_tool_definitions(),
            tool_choice={"type": "tool", "name": "extract_cicd_elements"},
        ),
    )

    elements: list[CICDElement] = []
    for tc in result.tool_calls:
        if tc.name == "extract_cicd_elements":
            for elem in tc.input.get("elements", []):
                elements.append(CICDElement(
                    cicd_file=path,
                    element_type=elem.get("element_type", cicd_type + "_job"),
                    element_name=elem.get("element_name", "unknown"),
                    line_start=elem.get("line_start", 1),
                    line_end=elem.get("line_end", 1),
                    referenced_paths=elem.get("referenced_paths", []),
                    referenced_commands=elem.get("referenced_commands", []),
                ))

    return elements, result.input_tokens, result.output_tokens


# --- Path extraction ---

# Common commands that are not file paths
_COMMON_COMMANDS = {
    "echo", "cd", "mkdir", "rm", "cp", "mv", "ls", "cat", "grep", "sed",
    "awk", "find", "chmod", "chown", "export", "source", "eval", "exec",
    "if", "then", "else", "fi", "for", "do", "done", "while", "case",
    "esac", "true", "false", "exit", "return", "set", "unset", "test",
    "pip", "pip3", "python", "python3", "node", "npm", "npx", "yarn",
    "pnpm", "cargo", "go", "make", "git", "docker", "kubectl",
    "curl", "wget", "tar", "unzip", "gzip",
    "sudo", "env", "bash", "sh", "zsh",
}


def _extract_paths_from_command(command: str) -> list[str]:
    """Extract file path-like tokens from a shell command."""
    paths: list[str] = []

    # Remove shell variable references and backtick/$(cmd) substitutions
    cleaned = re.sub(r"\$\{[^}]*\}", "", command)
    cleaned = re.sub(r"\$\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    cleaned = re.sub(r"\$\w+", "", cleaned)

    # Tokenize by whitespace
    tokens = cleaned.split()

    for token in tokens:
        # Strip quotes
        token = token.strip("'\"")

        # Skip flags
        if token.startswith("-"):
            continue

        # Skip URLs
        if re.match(r"https?://", token):
            continue

        # Skip empty or very short tokens
        if len(token) < 2:
            continue

        # Skip common commands
        if token.lower() in _COMMON_COMMANDS:
            continue

        # Skip tokens that look like options or environment variables
        if "=" in token and not "/" in token:
            continue

        # Include tokens that look like file paths
        if "/" in token or "." in token:
            # Must contain at least one path-like character
            if re.search(r"[a-zA-Z]", token):
                paths.append(token)

    return paths


# --- Path reference checking ---

def _check_path_references(
    config: Config,
    elements: list[CICDElement],
) -> list[CICDElement]:
    """Check which referenced paths actually exist in the repo.

    Populates missing_paths on each element.
    """
    # Build set of all known files: repo files + .github/ contents
    all_paths, _ = list_repo_files(config)
    known_files: set[str] = set()

    for p in all_paths:
        if not p.is_absolute():
            p = config.root_path / p
        rel = str(p.relative_to(config.root_path)).replace("\\", "/")
        known_files.add(rel)

    # Also scan .github/ since it's in ignore patterns
    github_dir = config.root_path / ".github"
    if github_dir.is_dir():
        for child in github_dir.rglob("*"):
            if child.is_file():
                rel = str(child.relative_to(config.root_path)).replace("\\", "/")
                known_files.add(rel)

    # Also add directories
    known_dirs: set[str] = set()
    for f in known_files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            known_dirs.add("/".join(parts[:i]))

    for element in elements:
        element.missing_paths = []
        for ref_path in element.referenced_paths:
            # Normalize
            normalized = ref_path.strip("./").replace("\\", "/")
            if not normalized:
                continue
            # Check if path or any parent dir exists
            if normalized not in known_files and normalized not in known_dirs:
                # Also check glob-style (e.g. src/**/*.py matches if src/ exists)
                base = normalized.split("*")[0].rstrip("/")
                if base and base not in known_files and base not in known_dirs:
                    element.missing_paths.append(ref_path)

    return elements


def _build_candidates(
    elements: list[CICDElement],
    file_contents: dict[str, str],
) -> list[CICDCandidate]:
    """Filter to elements with missing paths and build candidates."""
    candidates: list[CICDCandidate] = []

    for elem in elements:
        if not elem.missing_paths:
            continue

        full_content = file_contents.get(elem.cicd_file, "")
        lines = full_content.splitlines()
        elem_lines = lines[elem.line_start - 1:elem.line_end]
        elem_content = "\n".join(elem_lines)

        candidates.append(CICDCandidate(
            cicd_file=elem.cicd_file,
            element_name=elem.element_name,
            element_type=elem.element_type,
            line_start=elem.line_start,
            line_end=elem.line_end,
            missing_paths=elem.missing_paths,
            element_content=elem_content,
            full_file_content=full_content,
        ))

    return candidates


# --- LLM verification ---

_DEAD_CICD_SYSTEM_PROMPT = """You are analyzing CI/CD configuration files to identify stale or dead pipeline elements.

You are given CI/CD file content and a list of elements (jobs, targets) that reference paths which no longer exist in the repository. For each element, determine whether it is genuinely stale or still active.

## Still-active patterns (element is ALIVE despite missing paths)
- **Dependency installation**: pip install, npm install, cargo build — these don't reference local paths
- **Test runners**: pytest, jest, cargo test — test discovery is dynamic, doesn't need explicit paths
- **External deploy tools**: aws, gcloud, kubectl, docker — targets are external
- **Linters/formatters**: These operate on the whole repo, paths may be implicit
- **External actions/images**: GitHub Actions uses:, Docker images — these are external resources
- **Makefile phony targets**: clean, all, help — conventional targets without file outputs

## Dead patterns (element IS dead)
- References directories/files that were removed from the repo
- Builds a subproject that no longer exists
- Deploys to an environment that has been decommissioned
- Runs scripts that reference deleted files
- Test jobs targeting removed test directories

Missing paths are the PRIMARY signal, but evaluate holistically. An element
referencing one missing path among many valid operations is less likely to be dead
than one whose entire purpose depends on a missing path.

Use the verify_dead_cicd tool with a verdict for EVERY element."""


async def _verify_batch_async(
    provider: LLMProvider,
    config: Config,
    candidates: list[CICDCandidate],
    repo_file_summary: str,
) -> tuple[list[CICDVerification], int, int]:
    """Verify a batch of dead CI/CD candidates via one LLM call per CI/CD file.

    Returns (list[CICDVerification], input_tokens, output_tokens).
    """
    user_parts: list[str] = []

    cicd_file = candidates[0].cicd_file
    full_content = candidates[0].full_file_content
    user_parts.append(f"## CI/CD file: `{cicd_file}`\n```\n{full_content[:50000]}\n```\n")

    user_parts.append("## Elements with missing path references\n")
    for cand in candidates:
        user_parts.append(
            f"### `{cand.element_name}` ({cand.element_type}, lines {cand.line_start}-{cand.line_end})"
        )
        user_parts.append(f"Missing paths: {cand.missing_paths}")
        user_parts.append(f"```\n{cand.element_content[:5000]}\n```\n")

    user_parts.append(f"## Repository file listing (summary)\n```\n{repo_file_summary[:10000]}\n```\n")

    names_list = ", ".join(f"`{c.element_name}`" for c in candidates)
    user_parts.append(
        f"Provide a verdict for EVERY element listed ({names_list}) "
        "using the verify_dead_cicd tool."
    )

    # Build completeness validator
    expected_names = {c.element_name for c in candidates}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_dead_cicd":
            return []
        verdicts = tool_input.get("verdicts", [])
        got_names = {v.get("element_name") for v in verdicts}
        missing = expected_names - got_names
        return [f"Missing verdict for element '{name}'" for name in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_DEAD_CICD_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(1024, len(candidates) * 200),
            reservation_key="junk_cicd.verify",
            tools=get_dead_cicd_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_dead_cicd"},
            tool_input_validators=[check_completeness],
        ),
    )

    verifications: list[CICDVerification] = []
    cand_by_name = {c.element_name: c for c in candidates}

    for tool_call in result.tool_calls:
        if tool_call.name == "verify_dead_cicd":
            for verdict in tool_call.input.get("verdicts", []):
                elem_name = verdict.get("element_name", "")
                cand = cand_by_name.get(elem_name)
                if cand:
                    verifications.append(CICDVerification(
                        cicd_file=cand.cicd_file,
                        element_name=cand.element_name,
                        element_type=cand.element_type,
                        line_start=cand.line_start,
                        line_end=cand.line_end,
                        is_dead=verdict["is_dead"],
                        confidence=verdict["confidence"],
                        reason=verdict["reason"],
                        remediation=verdict["remediation"],
                    ))

    if not verifications:
        raise RuntimeError(
            f"LLM did not return verdicts for CI/CD elements: "
            f"{[c.element_name for c in candidates]}"
        )

    return verifications, result.input_tokens, result.output_tokens


def _build_repo_file_summary(config: Config) -> str:
    """Build a summary of repository files for LLM context."""
    all_paths, _ = list_repo_files(config)
    dirs: set[str] = set()
    files: list[str] = []

    for p in all_paths:
        if not p.is_absolute():
            p = config.root_path / p
        rel = str(p.relative_to(config.root_path)).replace("\\", "/")
        files.append(rel)
        # Collect directories
        parts = rel.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    # Also include .github/ contents
    github_dir = config.root_path / ".github"
    if github_dir.is_dir():
        for child in github_dir.rglob("*"):
            if child.is_file():
                rel = str(child.relative_to(config.root_path)).replace("\\", "/")
                files.append(rel)

    # Build directory tree summary (top-level dirs + counts)
    top_dirs: dict[str, int] = {}
    for f in files:
        top = f.split("/")[0] if "/" in f else f
        top_dirs[top] = top_dirs.get(top, 0) + 1

    summary_lines = ["Top-level directories:"]
    for d in sorted(top_dirs.keys()):
        summary_lines.append(f"  {d}/ ({top_dirs[d]} files)")

    # Include first ~200 file paths
    summary_lines.append("\nFiles:")
    for f in sorted(files)[:200]:
        summary_lines.append(f"  {f}")
    if len(files) > 200:
        summary_lines.append(f"  ... and {len(files) - 200} more files")

    return "\n".join(summary_lines)


# --- Full pipeline ---

_CICD_PARSERS: dict[str, Callable] = {
    "github_workflow": _parse_github_workflow,
    "makefile": _parse_makefile,
    "gitlab_ci": _parse_gitlab_ci,
}


async def detect_dead_cicd_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[CICDVerification]:
    """Detect stale CI/CD pipeline elements.

    Returns list of verified dead CI/CD elements.
    """
    cicd_files = discover_cicd_files(config)
    if not cicd_files:
        print("  [skip] No CI/CD configuration files found.", flush=True)
        return []

    print(f"  Found {len(cicd_files)} CI/CD file(s)", flush=True)

    # Parse all CI/CD files
    all_elements: list[CICDElement] = []
    file_contents: dict[str, str] = {}

    for abs_path, cicd_type in cicd_files:
        try:
            content = abs_path.read_text(errors="ignore")
        except OSError:
            continue

        rel_path = str(abs_path.relative_to(config.root_path)).replace("\\", "/")
        file_contents[rel_path] = content

        parser = _CICD_PARSERS.get(cicd_type)
        if parser:
            elements = parser(content, rel_path)
            all_elements.extend(elements)
        else:
            # Use Haiku for unsupported CI/CD systems
            try:
                haiku_elements, _in_tok, _out_tok = await _parse_cicd_via_haiku(
                    provider, content, rel_path, cicd_type, config,
                )
                all_elements.extend(haiku_elements)
                if haiku_elements:
                    print(f"  Haiku parsed {len(haiku_elements)} element(s) from {rel_path}", flush=True)
            except Exception as e:
                print(f"  [warn] Haiku CI/CD parsing failed for {rel_path}: {e}", flush=True)

    if not all_elements:
        print("  No CI/CD elements found to analyze.", flush=True)
        return []

    print(f"  Found {len(all_elements)} CI/CD element(s)", flush=True)

    # Check path references
    _check_path_references(config, all_elements)

    # Build candidates (elements with missing paths)
    candidates = _build_candidates(all_elements, file_contents)

    print(
        f"  {len(candidates)} element(s) with missing path references for LLM verification "
        f"(from {len(all_elements)} total elements)",
        flush=True,
    )

    if not candidates:
        return []

    # Build repo file summary for LLM context
    repo_summary = _build_repo_file_summary(config)

    # Group candidates by CI/CD file
    by_file: dict[str, list[CICDCandidate]] = {}
    for cand in candidates:
        by_file.setdefault(cand.cicd_file, []).append(cand)

    results: list[CICDVerification] = []
    completed_files = 0
    total_files = len(by_file)
    lock = asyncio.Lock()

    async def process_file(
        cicd_file: str,
        file_candidates: list[CICDCandidate],
    ) -> list[CICDVerification]:
        nonlocal completed_files

        try:
            verifications, _in_tok, _out_tok = await _verify_batch_async(
                provider, config, file_candidates, repo_summary,
            )

            async with lock:
                completed_files += 1
                dead_count = sum(1 for v in verifications if v.is_dead)
                for v in verifications:
                    if v.is_dead:
                        results.append(v)
                if on_progress:
                    on_progress(
                        completed_files, total_files,
                        Path(cicd_file),
                        f"{dead_count} dead",
                    )
            return verifications
        except Exception as e:
            async with lock:
                completed_files += 1
                if on_progress:
                    on_progress(
                        completed_files, total_files,
                        Path(cicd_file), "error",
                    )
            print(f"  [error] {cicd_file}: {e}", flush=True)
            return []

    await gather_with_buffer(
        [lambda cicd_file=cf, cands=cands: process_file(cicd_file, cands) for cf, cands in by_file.items()]
    )

    return results


class DeadCICDAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects stale CI/CD pipeline elements."""

    @property
    def name(self) -> str:
        return "dead_cicd"

    @property
    def description(self) -> str:
        return "Detect stale CI/CD pipeline elements"

    @property
    def cli_flag(self) -> str:
        return "dead-cicd"

    def analyze(self, config, on_progress=None, rate_limiter=None):
        """Sync wrapper — skip symbols-dir check (CI/CD doesn't need symbols)."""

        async def _run() -> JunkAnalysisResult:
            logging_provider, rl = create_runtime(config, rate_limiter=rate_limiter)
            try:
                return await self.analyze_async(
                    logging_provider, config, on_progress
                )
            finally:
                await logging_provider.close()

        return asyncio.run(_run())

    async def analyze_async(self, provider, config, on_progress=None):
        results = await detect_dead_cicd_async(provider, config, on_progress)
        findings = [
            JunkFinding(
                source_path=v.cicd_file,
                name=v.element_name,
                kind=v.element_type,
                category="dead_cicd",
                line_start=v.line_start,
                line_end=v.line_end,
                confidence=v.confidence,
                reason=v.reason,
                remediation=v.remediation,
                original_purpose=f"{v.element_type} `{v.element_name}`",
            )
            for v in results
        ]
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(results),
            analyzer_name=self.name,
        )
